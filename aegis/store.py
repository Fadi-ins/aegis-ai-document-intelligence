"""Transactional storage with PostgreSQL and a local SQLite development profile."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4


class Store:
    def __init__(self, location):
        self.location = location
        self.postgres = location.startswith(("postgresql://", "postgres://"))

    @contextmanager
    def connect(self):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            db = psycopg.connect(self.location, row_factory=dict_row, connect_timeout=5)
        else:
            Path(self.location).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            db = sqlite3.connect(self.location, timeout=10)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def execute(self, db, sql, args=()):
        return db.execute(sql.replace("?", "%s") if self.postgres else sql, args)

    def initialize(self):
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, digest TEXT NOT NULL,
                filename TEXT NOT NULL, pages INTEGER NOT NULL, original BYTEA NOT NULL,
                UNIQUE(owner, digest))""")
            db.execute("""CREATE TABLE IF NOT EXISTS passages (
                id TEXT PRIMARY KEY, doc TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                page INTEGER NOT NULL, body TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS passage_doc ON passages(doc)")
            if self.postgres:
                db.execute("""CREATE INDEX IF NOT EXISTS passage_fts ON passages
                    USING gin(to_tsvector('simple', body))""")
            else:
                db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts
                    USING fts5(id UNINDEXED, body)""")
                db.execute("""CREATE TRIGGER IF NOT EXISTS passage_insert AFTER INSERT ON passages
                    BEGIN INSERT INTO passage_fts(id, body) VALUES (new.id, new.body); END""")
                db.execute("""CREATE TRIGGER IF NOT EXISTS passage_delete AFTER DELETE ON passages
                    BEGIN DELETE FROM passage_fts WHERE id=old.id; END""")

    def save(self, owner, filename, data, parsed):
        digest = sha256(data).hexdigest()
        with self.connect() as db:
            doc_id = str(uuid4())
            result = self.execute(db, """INSERT INTO documents
                (id, owner, digest, filename, pages, original) VALUES (?,?,?,?,?,?)
                ON CONFLICT(owner, digest) DO NOTHING RETURNING id""",
                (doc_id, owner, digest, filename, parsed["pages"], data)).fetchone()
            if result:
                rows = [(str(uuid4()), doc_id, page, body) for page, body in parsed["passages"]]
                sql = "INSERT INTO passages(id, doc, page, body) VALUES (?,?,?,?)"
                db.cursor().executemany(sql.replace("?", "%s") if self.postgres else sql, rows)
            row = self.execute(db, """SELECT id, filename, pages FROM documents
                WHERE owner=? AND digest=?""", (owner, digest)).fetchone()
            return dict(row), bool(result)

    def get(self, owner, doc_id, *, file=False):
        with self.connect() as db:
            columns = "original" if file else "id, filename, pages"
            row = self.execute(db, f"SELECT {columns} FROM documents WHERE owner=? AND id=?",
                               (owner, doc_id)).fetchone()
            return dict(row) if row else None

    def delete(self, owner, doc_id):
        with self.connect() as db:
            return self.execute(db, "DELETE FROM documents WHERE owner=? AND id=?",
                                (owner, doc_id)).rowcount

    def search(self, owner, doc_ids, terms):
        marks = ",".join("?" for _ in doc_ids)
        scope = f"d.owner=? AND d.id IN ({marks})"
        with self.connect() as db:
            count = self.execute(db, f"SELECT count(*) AS n FROM documents d WHERE {scope}",
                                 (owner, *doc_ids)).fetchone()["n"]
            if count != len(doc_ids):
                raise LookupError
            if not terms:
                return []
            select = """SELECT p.id, d.id AS document_id, d.filename, p.page, p.body
                        FROM passages p JOIN documents d ON d.id=p.doc """
            if self.postgres:
                query = " | ".join(terms)
                sql = select + f"""CROSS JOIN to_tsquery('simple', ?) q
                    WHERE {scope} AND to_tsvector('simple', p.body) @@ q
                    ORDER BY ts_rank(to_tsvector('simple', p.body), q) DESC, p.id LIMIT 5"""
                args = (query, owner, *doc_ids)
            else:
                query = " OR ".join(f'"{term}"' for term in terms)
                sql = select + f"""JOIN passage_fts ON passage_fts.id=p.id
                    WHERE {scope} AND passage_fts MATCH ? ORDER BY rank, p.id LIMIT 5"""
                args = (owner, *doc_ids, query)
            return [dict(row) for row in self.execute(db, sql, args)]
