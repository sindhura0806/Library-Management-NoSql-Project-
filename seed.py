"""Run once:  python seed.py   -> loads sample data into MongoDB and Neo4j."""
from datetime import date, timedelta

from db import (books, members, transactions, mdb, run_cypher, init_graph,
                graph_sync_book, graph_sync_member, graph_borrow)

BOOKS = [
    ("B001", "Introduction to Algorithms", ["Thomas H. Cormen", "Charles E. Leiserson"], "Algorithms"),
    ("B002", "Artificial Intelligence: A Modern Approach", ["Stuart Russell", "Peter Norvig"], "AI"),
    ("B003", "Deep Learning", ["Ian Goodfellow", "Yoshua Bengio"], "AI"),
    ("B004", "Clean Code", ["Robert C. Martin"], "Software Engineering"),
    ("B005", "The Pragmatic Programmer", ["Andrew Hunt", "David Thomas"], "Software Engineering"),
    ("B006", "Database System Concepts", ["Abraham Silberschatz"], "Databases"),
    ("B007", "NoSQL Distilled", ["Pramod J. Sadalage", "Martin Fowler"], "Databases"),
    ("B008", "Python Crash Course", ["Eric Matthes"], "Programming"),
    ("B009", "Computer Networks", ["Andrew S. Tanenbaum"], "Networking"),
    ("B010", "Hands-On Machine Learning", ["Aurelien Geron"], "AI"),
]

MEMBERS = [
    ("M001", "Ananya Rao", "ananya@example.com", "CSE"),
    ("M002", "Ravi Teja", "ravi@example.com", "ECE"),
    ("M003", "Priya Sharma", "priya@example.com", "CSE"),
    ("M004", "Kiran Kumar", "kiran@example.com", "IT"),
    ("M005", "Meena Devi", "meena@example.com", "CSE"),
]

# (member, book, issued N days ago, returned?)
ISSUES = [
    ("M001", "B001", 40, True), ("M001", "B002", 30, True), ("M001", "B003", 5, False),
    ("M002", "B002", 35, True), ("M002", "B003", 25, True), ("M002", "B010", 4, False),
    ("M003", "B004", 33, True), ("M003", "B005", 28, True), ("M003", "B008", 20, False),
    ("M004", "B006", 31, True), ("M004", "B007", 22, True), ("M004", "B002", 3, False),
    ("M005", "B003", 29, True), ("M005", "B010", 21, True), ("M005", "B001", 2, False),
]

LOAN_DAYS, COPIES = 14, 3


def main():
    # clean slate
    for col in (books, members, transactions, mdb.counters):
        col.delete_many({})
    run_cypher("MATCH (n) DETACH DELETE n")
    init_graph()

    book_docs = {}
    for bid, title, authors, genre in BOOKS:
        doc = {"book_id": bid, "title": title, "authors": authors, "genre": genre,
               "isbn": f"978000000{bid[1:]}", "copies_available": COPIES}
        book_docs[bid] = doc

    for mid, name, email, branch in MEMBERS:
        doc = {"member_id": mid, "name": name, "email": email, "branch": branch}
        members.insert_one(doc)
        graph_sync_member(doc)

    today = date.today()
    for n, (mid, bid, ago, returned) in enumerate(ISSUES, start=1):
        issue = today - timedelta(days=ago)
        due = issue + timedelta(days=LOAN_DAYS)
        ret = issue + timedelta(days=10) if returned else None
        transactions.insert_one({
            "txn_id": f"T{n:03d}", "member_id": mid, "book_id": bid,
            "issue_date": issue.isoformat(), "due_date": due.isoformat(),
            "return_date": ret.isoformat() if ret else None, "fine": 0,
        })
        if not returned:
            book_docs[bid]["copies_available"] -= 1

    for doc in book_docs.values():
        books.insert_one(doc)
        graph_sync_book(doc)

    for n, (mid, bid, ago, _) in enumerate(ISSUES, start=1):
        graph_borrow(mid, bid, (today - timedelta(days=ago)).isoformat())

    # counters so new ids continue after the seeded ones
    mdb.counters.insert_many([
        {"_id": "book", "seq": len(BOOKS)},
        {"_id": "member", "seq": len(MEMBERS)},
        {"_id": "txn", "seq": len(ISSUES)},
    ])
    print("Seeded:", books.count_documents({}), "books,", members.count_documents({}),
          "members,", transactions.count_documents({}), "transactions")


if __name__ == "__main__":
    main()
