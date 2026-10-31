"""Database layer: MongoDB (operational data) + Neo4j (relationships / recommendations)."""
import os

from neo4j import GraphDatabase
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# ---------- MongoDB ----------
mongo_client = MongoClient(MONGO_URI)
mdb = mongo_client["library_db"]
books = mdb["books"]
members = mdb["members"]
transactions = mdb["transactions"]

# ---------- Neo4j ----------
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def run_cypher(query, **params):
    """Run a Cypher query and return a list of dicts."""
    with driver.session() as session:
        return [record.data() for record in session.run(query, **params)]


def init_graph():
    """Uniqueness constraints (also create indexes)."""
    run_cypher("CREATE CONSTRAINT book_id IF NOT EXISTS FOR (b:Book) REQUIRE b.book_id IS UNIQUE")
    run_cypher("CREATE CONSTRAINT member_id IF NOT EXISTS FOR (m:Member) REQUIRE m.member_id IS UNIQUE")
    run_cypher("CREATE CONSTRAINT author_name IF NOT EXISTS FOR (a:Author) REQUIRE a.name IS UNIQUE")
    run_cypher("CREATE CONSTRAINT genre_name IF NOT EXISTS FOR (g:Genre) REQUIRE g.name IS UNIQUE")


# ---------- Keep Neo4j in sync with MongoDB ----------
def graph_sync_book(book):
    """Create/update Book node, its Genre and Author nodes and relationships."""
    run_cypher(
        """
        MERGE (b:Book {book_id: $book_id})
        SET b.title = $title
        MERGE (g:Genre {name: $genre})
        MERGE (b)-[:BELONGS_TO]->(g)
        WITH b
        UNWIND $authors AS author_name
        MERGE (a:Author {name: author_name})
        MERGE (b)-[:WRITTEN_BY]->(a)
        """,
        book_id=book["book_id"], title=book["title"],
        genre=book["genre"], authors=book["authors"],
    )


def graph_sync_member(member):
    run_cypher(
        "MERGE (m:Member {member_id: $member_id}) SET m.name = $name",
        member_id=member["member_id"], name=member["name"],
    )


def graph_borrow(member_id, book_id, issue_date):
    run_cypher(
        """
        MATCH (m:Member {member_id: $member_id}), (b:Book {book_id: $book_id})
        MERGE (m)-[r:BORROWED]->(b)
        SET r.date = $issue_date
        """,
        member_id=member_id, book_id=book_id, issue_date=issue_date,
    )
