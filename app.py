"""Library Management & Book Recommendation System
MongoDB -> books, members, transactions (operational data)
Neo4j   -> Member/Book/Author/Genre graph (recommendations)
"""
import re
from datetime import date, timedelta

from flask import Flask, flash, redirect, render_template, request, url_for
from pymongo import ReturnDocument

from db import (books, members, transactions, mdb, run_cypher, init_graph,
                graph_sync_book, graph_sync_member, graph_borrow)

app = Flask(__name__)
app.secret_key = "change-me"

LOAN_DAYS = 14
FINE_PER_DAY = 2  # rupees per late day

init_graph()


def next_id(name, prefix):
    """Auto-increment ids like B011, M006, T016 using a counters collection."""
    doc = mdb.counters.find_one_and_update(
        {"_id": name}, {"$inc": {"seq": 1}}, upsert=True,
        return_document=ReturnDocument.AFTER)
    return f"{prefix}{doc['seq']:03d}"


# ------------------------------------------------------------------ Dashboard
@app.route("/")
def index():
    stats = {
        "books": books.count_documents({}),
        "members": members.count_documents({}),
        "issued": transactions.count_documents({"return_date": None}),
        "edges": run_cypher("MATCH ()-[r:BORROWED]->() RETURN count(r) AS c")[0]["c"],
    }
    return render_template("index.html", stats=stats)


# ---------------------------------------------------------------------- Books
@app.route("/books", methods=["GET", "POST"])
def books_page():
    if request.method == "POST":                                   # CREATE
        doc = {
            "book_id": next_id("book", "B"),
            "title": request.form["title"].strip(),
            "authors": [a.strip() for a in request.form["authors"].split(",") if a.strip()],
            "genre": request.form["genre"].strip(),
            "isbn": request.form["isbn"].strip(),
            "copies_available": int(request.form["copies"]),
        }
        books.insert_one(doc)          # MongoDB
        graph_sync_book(doc)           # Neo4j
        flash(f"Book {doc['book_id']} added.", "ok")
        return redirect(url_for("books_page"))

    q = request.args.get("q", "").strip()                          # READ / search
    query = {}
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query = {"$or": [{"title": rx}, {"genre": rx}, {"authors": rx}]}
    return render_template("books.html", books=list(books.find(query).sort("book_id")), q=q)


@app.route("/books/<book_id>/update", methods=["POST"])            # UPDATE
def update_book(book_id):
    title = request.form["title"].strip()
    copies = int(request.form["copies"])
    books.update_one({"book_id": book_id},
                     {"$set": {"title": title, "copies_available": copies}})
    run_cypher("MATCH (b:Book {book_id:$id}) SET b.title=$title", id=book_id, title=title)
    flash(f"Book {book_id} updated.", "ok")
    return redirect(url_for("books_page"))


@app.route("/books/<book_id>/delete", methods=["POST"])            # DELETE
def delete_book(book_id):
    if transactions.count_documents({"book_id": book_id, "return_date": None}):
        flash("Cannot delete: this book is currently issued.", "error")
    else:
        books.delete_one({"book_id": book_id})
        run_cypher("MATCH (b:Book {book_id:$id}) DETACH DELETE b", id=book_id)
        flash(f"Book {book_id} deleted.", "ok")
    return redirect(url_for("books_page"))


# -------------------------------------------------------------------- Members
@app.route("/members", methods=["GET", "POST"])
def members_page():
    if request.method == "POST":
        doc = {
            "member_id": next_id("member", "M"),
            "name": request.form["name"].strip(),
            "email": request.form["email"].strip(),
            "branch": request.form["branch"].strip(),
        }
        members.insert_one(doc)
        graph_sync_member(doc)
        flash(f"Member {doc['member_id']} added.", "ok")
        return redirect(url_for("members_page"))
    return render_template("members.html", members=list(members.find().sort("member_id")))


@app.route("/members/<member_id>/update", methods=["POST"])
def update_member(member_id):
    name = request.form["name"].strip()
    members.update_one({"member_id": member_id},
                       {"$set": {"name": name, "branch": request.form["branch"].strip()}})
    run_cypher("MATCH (m:Member {member_id:$id}) SET m.name=$name", id=member_id, name=name)
    flash(f"Member {member_id} updated.", "ok")
    return redirect(url_for("members_page"))


@app.route("/members/<member_id>/delete", methods=["POST"])
def delete_member(member_id):
    if transactions.count_documents({"member_id": member_id, "return_date": None}):
        flash("Cannot delete: member still has unreturned books.", "error")
    else:
        members.delete_one({"member_id": member_id})
        run_cypher("MATCH (m:Member {member_id:$id}) DETACH DELETE m", id=member_id)
        flash(f"Member {member_id} deleted.", "ok")
    return redirect(url_for("members_page"))


# --------------------------------------------------------------- Transactions
@app.route("/transactions")
def transactions_page():
    names = {m["member_id"]: m["name"] for m in members.find()}
    titles = {b["book_id"]: b["title"] for b in books.find()}
    txns = list(transactions.find().sort("txn_id", -1))
    return render_template("transactions.html", txns=txns, names=names, titles=titles,
                           members=list(members.find().sort("member_id")),
                           books=list(books.find().sort("book_id")),
                           today=date.today().isoformat())


@app.route("/issue", methods=["POST"])
def issue():
    member_id, book_id = request.form["member_id"], request.form["book_id"]
    if not members.find_one({"member_id": member_id}):
        flash("Member not found.", "error")
        return redirect(url_for("transactions_page"))
    # atomic: only decrement if a copy is available
    book = books.find_one_and_update(
        {"book_id": book_id, "copies_available": {"$gt": 0}},
        {"$inc": {"copies_available": -1}})
    if not book:
        flash("No copies available for this book.", "error")
        return redirect(url_for("transactions_page"))
    today = date.today()
    txn = {
        "txn_id": next_id("txn", "T"), "member_id": member_id, "book_id": book_id,
        "issue_date": today.isoformat(),
        "due_date": (today + timedelta(days=LOAN_DAYS)).isoformat(),
        "return_date": None, "fine": 0,
    }
    transactions.insert_one(txn)                           # MongoDB
    graph_borrow(member_id, book_id, today.isoformat())    # Neo4j relationship
    flash(f"Issued '{book['title']}' ({txn['txn_id']}). Due {txn['due_date']}.", "ok")
    return redirect(url_for("transactions_page"))


@app.route("/return/<txn_id>", methods=["POST"])
def return_book(txn_id):
    txn = transactions.find_one({"txn_id": txn_id, "return_date": None})
    if not txn:
        flash("Transaction not found or already returned.", "error")
        return redirect(url_for("transactions_page"))
    today = date.today()
    late_days = max(0, (today - date.fromisoformat(txn["due_date"])).days)
    fine = late_days * FINE_PER_DAY
    transactions.update_one({"txn_id": txn_id},
                            {"$set": {"return_date": today.isoformat(), "fine": fine}})
    books.update_one({"book_id": txn["book_id"]}, {"$inc": {"copies_available": 1}})
    flash(f"Returned. Fine: Rs {fine}.", "ok")
    return redirect(url_for("transactions_page"))


# ------------------------------------------------------------ Recommendations
def hydrate(rows):
    """Neo4j gives book_id + score; fetch full book details from MongoDB."""
    ids = [r["book_id"] for r in rows]
    docs = {b["book_id"]: b for b in books.find({"book_id": {"$in": ids}})}
    return [{**docs[r["book_id"]], "score": r["score"]} for r in rows if r["book_id"] in docs]


@app.route("/recommend")
def recommend():
    member_id = request.args.get("member_id", "")
    all_members = list(members.find().sort("member_id"))
    collab = content = history = []
    member = None
    if member_id:
        member = members.find_one({"member_id": member_id})
        history = hydrate([{"book_id": r["book_id"], "score": ""} for r in run_cypher(
            "MATCH (:Member {member_id:$id})-[:BORROWED]->(b:Book) RETURN b.book_id AS book_id",
            id=member_id)])
        # 1) Collaborative filtering: what did people with similar history borrow?
        collab = hydrate(run_cypher(
            """
            MATCH (m:Member {member_id:$id})-[:BORROWED]->(:Book)<-[:BORROWED]-(o:Member)
                  -[:BORROWED]->(rec:Book)
            WHERE o <> m AND NOT (m)-[:BORROWED]->(rec)
            RETURN rec.book_id AS book_id, COUNT(DISTINCT o) AS score
            ORDER BY score DESC LIMIT 5
            """, id=member_id))
        # 2) Content based: books sharing a genre/author with books already read
        content = hydrate(run_cypher(
            """
            MATCH (m:Member {member_id:$id})-[:BORROWED]->(:Book)
                  -[:BELONGS_TO|WRITTEN_BY]->(x)<-[:BELONGS_TO|WRITTEN_BY]-(rec:Book)
            WHERE NOT (m)-[:BORROWED]->(rec)
            RETURN rec.book_id AS book_id, COUNT(*) AS score
            ORDER BY score DESC LIMIT 5
            """, id=member_id))
    return render_template("recommend.html", members=all_members, member=member,
                           member_id=member_id, collab=collab, content=content, history=history)


# -------------------------------------------------------------------- Reports
@app.route("/reports")
def reports():
    today = date.today().isoformat()
    # MongoDB aggregation: most borrowed books
    top_books = list(transactions.aggregate([
        {"$group": {"_id": "$book_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}, {"$limit": 5},
        {"$lookup": {"from": "books", "localField": "_id",
                     "foreignField": "book_id", "as": "book"}},
        {"$unwind": "$book"},
        {"$project": {"_id": 0, "title": "$book.title", "count": 1}},
    ]))
    # MongoDB query: overdue, not returned
    overdue = list(transactions.find({"return_date": None, "due_date": {"$lt": today}}))
    # Neo4j: genre popularity
    genres = run_cypher(
        """MATCH (:Member)-[:BORROWED]->(:Book)-[:BELONGS_TO]->(g:Genre)
           RETURN g.name AS genre, COUNT(*) AS borrows ORDER BY borrows DESC""")
    # Neo4j: members with similar taste
    similar = run_cypher(
        """MATCH (a:Member)-[:BORROWED]->(b:Book)<-[:BORROWED]-(c:Member)
           WHERE a.member_id < c.member_id
           RETURN a.name AS member1, c.name AS member2, COUNT(b) AS common
           ORDER BY common DESC LIMIT 5""")
    return render_template("reports.html", top_books=top_books, overdue=overdue,
                           genres=genres, similar=similar)


if __name__ == "__main__":
    app.run(debug=True)
