# Library Management and Book Recommendation System
NoSQL PBL - Project 7 (MongoDB + Neo4j), built with Python Flask.

## 1. Start the databases (Docker, easiest)
    docker run -d --name mongo -p 27017:27017 mongo:7
    docker run -d --name neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:5

(Or install MongoDB Community + Neo4j Desktop. If your Neo4j password differs, set
NEO4J_PASSWORD, e.g. `set NEO4J_PASSWORD=yourpass` on Windows.)

## 2. Install and run
    pip install -r requirements.txt
    python seed.py        # loads sample data into both databases
    python app.py         # open http://127.0.0.1:5000

## 3. Queries to screenshot for the report

### MongoDB (mongosh, database: library_db)
    use library_db
    db.books.insertOne({book_id:"B100", title:"Test Book", authors:["A"], genre:"AI", isbn:"1", copies_available:2})
    db.books.find({genre:"AI"})
    db.books.updateOne({book_id:"B100"}, {$set:{copies_available:5}})
    db.books.deleteOne({book_id:"B100"})
    db.transactions.find({return_date:null})
    db.transactions.aggregate([{$group:{_id:"$book_id", count:{$sum:1}}},{$sort:{count:-1}}])

### Neo4j 
    CREATE (b:Book {book_id:"B100", title:"Test Book"})
    MATCH (m:Member {member_id:"M001"})-[:BORROWED]->(b:Book) RETURN m, b
    MATCH (b:Book {book_id:"B100"}) SET b.title = "Updated Title"
    MATCH (b:Book {book_id:"B100"}) DETACH DELETE b
    MATCH (m:Member {member_id:"M001"})-[:BORROWED]->(:Book)<-[:BORROWED]-(o:Member)-[:BORROWED]->(rec:Book)
    WHERE NOT (m)-[:BORROWED]->(rec) RETURN rec.title, COUNT(*) AS score ORDER BY score DESC
    MATCH p=(:Member)-[:BORROWED]->(:Book)-[:BELONGS_TO]->(:Genre) RETURN p LIMIT 25
