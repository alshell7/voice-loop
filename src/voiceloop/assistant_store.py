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
        self.db.create_function(
            "casefold", 1, lambda value: str(value or "").casefold(), deterministic=True
        )
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS jobs_created "
            "ON jobs(json_extract(body, '$.created_at') DESC, id DESC)"
        )
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

    def page(self, kind=None, query="", page=1, page_size=20):
        """Read a bounded slice of the full journal, with literal text search."""
        if kind not in (None, "summary"):
            raise ValueError("Job kind must be summary or omitted.")
        if not isinstance(query, str) or len(query) > 1000:
            raise ValueError("Search must be text of at most 1,000 characters.")
        if type(page) is not int or type(page_size) is not int:
            raise ValueError("Page and page size must be integers.")
        page_size = min(100, max(1, page_size))
        query = query.strip().casefold()
        filters, parameters = [], []
        if kind == "summary":
            filters.append(
                "COALESCE(json_extract(body, '$.delivery_status'), 'not_requested') "
                "<> 'not_requested'"
            )
        if query:
            filters.append(
                "("
                + " OR ".join(
                    f"instr(casefold(json_extract(body, '$.{field}')), ?) > 0"
                    for field in ("target_name", "objective", "summary")
                )
                + ")"
            )
            parameters.extend([query] * 3)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with self.lock:
            total = self.db.execute("SELECT count(*) FROM jobs" + where, parameters).fetchone()[0]
            pages = max(1, (total + page_size - 1) // page_size)
            page = min(pages, max(1, page))
            rows = self.db.execute(
                "SELECT body FROM jobs"
                + where
                + " ORDER BY json_extract(body, '$.created_at') DESC, id DESC LIMIT ? OFFSET ?",
                [*parameters, page_size, (page - 1) * page_size],
            ).fetchall()
        return {
            "items": [json.loads(row[0]) for row in rows],
            "total": total,
            "page": page,
            "pages": pages,
        }

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
