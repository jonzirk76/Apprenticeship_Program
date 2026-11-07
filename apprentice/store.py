"""Small local persistence layer. Observations and estimates stay separate."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS issues (
                id INTEGER PRIMARY KEY, repo TEXT NOT NULL, number INTEGER NOT NULL,
                url TEXT NOT NULL, title TEXT NOT NULL, observed TEXT NOT NULL,
                retrieved_at TEXT NOT NULL, UNIQUE(repo, number));
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY, issue_id INTEGER NOT NULL REFERENCES issues(id),
                source TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY, issue_id INTEGER NOT NULL REFERENCES issues(id),
                level TEXT NOT NULL DEFAULT 'librarian', status TEXT NOT NULL DEFAULT 'selected',
                implementation_complete INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS packets (
                id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
                data TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
                data TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, issue_id INTEGER REFERENCES issues(id),
                kind TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS http_cache (
                url TEXT PRIMARY KEY, data TEXT NOT NULL, retrieved_at TEXT NOT NULL);
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def observe(self, observed):
        issue = observed["issue"]
        repo = observed["repository"]["full_name"]
        with self.db:
            self.db.execute("""INSERT INTO issues(repo,number,url,title,observed,retrieved_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(repo,number) DO UPDATE SET
                url=excluded.url,title=excluded.title,observed=excluded.observed,
                retrieved_at=excluded.retrieved_at""",
                (repo, issue["number"], issue["html_url"], issue["title"],
                 json.dumps(observed), observed["retrieved_at"]))
            row = self.db.execute("SELECT id FROM issues WHERE repo=? AND number=?",
                                  (repo, issue["number"])).fetchone()
            self.event(row["id"], "observed", observed)
        return row["id"]

    def assess(self, issue_id, assessment, source="heuristic-v1"):
        with self.db:
            self.db.execute("INSERT INTO assessments(issue_id,source,data,created_at) VALUES(?,?,?,?)",
                            (issue_id, source, json.dumps(assessment), now()))

    def issue(self, issue_id):
        row = self.db.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        if not row:
            raise ValueError(f"No local issue with ID {issue_id}")
        result = dict(row)
        result["observed"] = json.loads(row["observed"])
        a = self.db.execute("SELECT data,source FROM assessments WHERE issue_id=? ORDER BY id DESC LIMIT 1",
                            (issue_id,)).fetchone()
        result["assessment"] = json.loads(a["data"]) if a else None
        result["assessment_source"] = a["source"] if a else None
        return result

    def candidates(self):
        return [self.issue(r[0]) for r in self.db.execute("SELECT id FROM issues ORDER BY id")]

    def select(self, issue_id):
        self.issue(issue_id)
        with self.db:
            cur = self.db.execute("INSERT INTO sessions(issue_id,created_at) VALUES(?,?)", (issue_id, now()))
            self.event(issue_id, "selected", {"session_id": cur.lastrowid})
        return self.session()

    def session(self):
        row = self.db.execute("SELECT * FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            raise ValueError("Select a candidate first: apprentice select ID")
        return dict(row)

    def mode(self, level, completed=False):
        session = self.session()
        if level == "reviewer" and not (completed or session["implementation_complete"]):
            raise ValueError("Reviewer requires an explicit --completed declaration")
        with self.db:
            self.db.execute("UPDATE sessions SET level=?,implementation_complete=? WHERE id=?",
                            (level, int(completed or session["implementation_complete"]), session["id"]))
            self.event(session["issue_id"], "assistance", {"level": level})
        return self.session()

    def artifact(self, kind, data):
        if kind not in {"packets", "reviews"}:
            raise ValueError("Unknown artifact type")
        session = self.session()
        with self.db:
            self.db.execute(f"INSERT INTO {kind}(session_id,data,created_at) VALUES(?,?,?)",
                            (session["id"], json.dumps(data), now()))

    def event(self, issue_id, kind, data):
        with self.db:
            self.db.execute("INSERT INTO events(issue_id,kind,data,created_at) VALUES(?,?,?,?)",
                            (issue_id, kind, json.dumps(data), now()))

    def cache_get(self, url):
        row = self.db.execute("SELECT * FROM http_cache WHERE url=?", (url,)).fetchone()
        return (json.loads(row["data"]), row["retrieved_at"]) if row else None

    def cache_put(self, url, data):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO http_cache VALUES(?,?,?)", (url, json.dumps(data), now()))

    def history(self):
        events = [dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY id")]
        for event in events:
            event["data"] = json.loads(event["data"])
        artifacts = {}
        for table in ("packets", "reviews"):
            artifacts[table] = [dict(r) for r in self.db.execute(f"SELECT * FROM {table} ORDER BY id")]
            for row in artifacts[table]:
                row["data"] = json.loads(row["data"])
        return {"events": events, **artifacts}
