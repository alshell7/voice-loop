"""Durable job journal. Uncertain external actions are never retried on restart."""

import json
import sqlite3
import threading
from pathlib import Path

TERMINAL = {"completed", "failed", "cancelled", "expired", "interrupted"}


class AssistantStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS identities (scope TEXT, participant TEXT, url TEXT, "
            "PRIMARY KEY(scope, participant, url))"
        )
        self.db.commit()
        for job in self.list():
            if job["state"] not in TERMINAL | {"scheduled", "queued"}:
                job.update(state="interrupted", error="Voice Loop restarted. Call was not retried.")
                if job.get("delivery_status") == "sending":
                    job["delivery_status"] = "ambiguous"
                self.put(job)
            elif job.get("delivery_status") in {"sending", "generating"}:
                job["delivery_status"] = "interrupted"
                self.put(job)

    def put(self, job):
        body = json.dumps(job, ensure_ascii=False, allow_nan=False)
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?)", (job["id"], body))

    def get(self, job_id):
        with self.lock:
            row = self.db.execute("SELECT body FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown assistant job.")
        return json.loads(row[0])

    def list(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT body FROM jobs")]

    def close(self):
        with self.lock:
            self.db.close()

    def learn(self, scope, participant, url):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO identities VALUES (?, ?, ?)", (scope, participant, url)
            )

    def resolve(self, scope, participant):
        with self.lock:
            rows = self.db.execute(
                "SELECT url FROM identities WHERE scope=? AND participant=?", (scope, participant)
            ).fetchall()
        return rows[0][0] if len(rows) == 1 else ""
