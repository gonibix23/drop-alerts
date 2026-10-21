from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .models import Event, FetchResult, Item, canonical_json, fingerprint, utcnow
from .identities import announcement_url


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,initialized INTEGER NOT NULL DEFAULT 0,
          last_attempt TEXT,last_success TEXT,last_error TEXT,failures INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS items(source TEXT,id TEXT,revision INTEGER NOT NULL,digest TEXT NOT NULL,
          payload TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(source,id));
        CREATE TABLE IF NOT EXISTS item_history(source TEXT,id TEXT,revision INTEGER,payload TEXT,created REAL,
          PRIMARY KEY(source,id,revision));
        CREATE TABLE IF NOT EXISTS bootstrap_items(source TEXT,id TEXT,PRIMARY KEY(source,id));
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,source TEXT,item_id TEXT,event_type TEXT,
          fingerprint TEXT,payload TEXT,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox(event_id TEXT PRIMARY KEY REFERENCES events(id),status TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,last_error TEXT,delivered REAL);
        CREATE INDEX IF NOT EXISTS outbox_due ON outbox(status,next_attempt);
        CREATE TABLE IF NOT EXISTS notification_history(id INTEGER PRIMARY KEY,event_id TEXT,
          attempt INTEGER,outcome TEXT,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS analysis_cache(key TEXT PRIMARY KEY,payload TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS analysis_jobs(id TEXT PRIMARY KEY,source TEXT,item_id TEXT,digest TEXT,
          task TEXT,content TEXT,status TEXT,attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt REAL NOT NULL DEFAULT 0,created REAL NOT NULL,result TEXT);
        CREATE INDEX IF NOT EXISTS analysis_due ON analysis_jobs(status,next_attempt,created);
        CREATE TABLE IF NOT EXISTS event_jobs(event_id TEXT PRIMARY KEY REFERENCES events(id),job_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS diagnostics(id INTEGER PRIMARY KEY,component TEXT,code TEXT,detail TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS http_cache(url TEXT PRIMARY KEY,body TEXT,etag TEXT,last_modified TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS announcement_claims(identity TEXT PRIMARY KEY,event_id TEXT NOT NULL,created REAL NOT NULL);
        INSERT OR IGNORE INTO meta VALUES('schema_version','1');
        """)
        version = self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        if version not in ("1", "2"):
            raise RuntimeError("Versión de base de datos no compatible")
        if version == "1":
            # Additive migration: preserve historical deliveries and silent baseline
            # identities before enabling feeds that may reference those articles.
            with self.transaction():
                rows = self.db.execute("SELECT id,payload,item_id FROM events WHERE event_type IN ('publication.new','announcement.new') ORDER BY created").fetchall()
                for row in rows:
                    event = Event(**json.loads(row["payload"])) if row["payload"] else None
                    identity = self.announcement_identity(event) if event else announcement_url(row["item_id"])
                    if identity:
                        self.db.execute("INSERT OR IGNORE INTO announcement_claims VALUES(?,?,?)", (identity, row["id"], time.time()))
                self.db.execute("UPDATE meta SET value='2' WHERE key='schema_version'")

    @staticmethod
    def announcement_identity(event: Event) -> str | None:
        if event.event_type not in ("announcement.new", "publication.new"):
            return None
        data = event.data["current"].get("data", {})
        return announcement_url(data.get("announcement_url", "")) or announcement_url(event.url)

    def close(self):
        self.db.close()

    def get_meta(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, str(value)))
        self.db.commit()

    def get_source_items(self, source: str) -> list[Item]:
        return [Item(**json.loads(row[0])) for row in self.db.execute("SELECT payload FROM items WHERE source=? ORDER BY id", (source,))]

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    def diagnostic(self, component: str, code: str, detail: str):
        # Callers pass short codes, never exception strings containing credentials/URLs.
        self.db.execute("INSERT INTO diagnostics(component,code,detail,created) VALUES(?,?,?,?)", (component[:80], code[:80], detail[:240], time.time()))
        self.db.execute("DELETE FROM diagnostics WHERE id NOT IN (SELECT id FROM diagnostics ORDER BY id DESC LIMIT 1000)")
        self.db.commit()

    def source_attempt(self, source: str):
        self.db.execute("INSERT OR IGNORE INTO sources(id) VALUES(?)", (source,))
        self.db.execute("UPDATE sources SET last_attempt=? WHERE id=?", (utcnow(), source))
        self.db.commit()

    def source_error(self, source: str, code: str):
        self.db.execute("UPDATE sources SET last_error=?,failures=failures+1 WHERE id=?", (code, source))
        self.db.commit()
        self.diagnostic(source, "source_failed", code)

    def item(self, source: str, item_id: str) -> tuple[Item | None, int]:
        row = self.db.execute("SELECT payload,revision FROM items WHERE source=? AND id=?", (source, item_id)).fetchone()
        return (Item(**json.loads(row["payload"])), row["revision"]) if row else (None, 0)

    def ingest(self, source: str, result: FetchResult, detector, rules, settings) -> int:
        # Validate the entire batch before changing any persisted state.
        if not result.items and not result.not_modified:
            raise ValueError("Respuesta vacía: no se confirma una línea base")
        if len({x.id for x in result.items}) != len(result.items) or any(x.source != source for x in result.items):
            raise ValueError("Elementos duplicados o fuente incorrecta")
        count = 0
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO sources(id) VALUES(?)", (source,))
            initialized = self.db.execute("SELECT initialized FROM sources WHERE id=?", (source,)).fetchone()[0]
            silent = not initialized and settings.bootstrap_mode == "silent"
            # A new discovery channel can expose years of articles even when the
            # adapter's original source already has a baseline. Mark each inventory
            # atomically, so a restart cannot import it as newly published content.
            for channel, identities in result.metadata.get("discovery_inventories", {}).items():
                marker = f"source_inventory:{source}:{channel}"
                if not self.get_meta(marker):
                    if settings.bootstrap_mode == "silent":
                        for item_id in identities:
                            if isinstance(item_id, str):
                                self.db.execute("INSERT OR IGNORE INTO bootstrap_items VALUES(?,?)", (source, item_id))
                    self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (marker, "1"))
            if silent:
                for item_id in result.metadata.get("bootstrap_ids", []):
                    if isinstance(item_id, str):
                        self.db.execute("INSERT OR IGNORE INTO bootstrap_items VALUES(?,?)", (source, item_id))
            for current in result.items:
                previous, revision = self.item(source, current.id)
                historical = previous is None and self.db.execute("SELECT 1 FROM bootstrap_items WHERE source=? AND id=?", (source, current.id)).fetchone() is not None
                if previous and current.digest == previous.digest:
                    continue
                revision += 1
                payload = canonical_json(asdict(current))
                self.db.execute("INSERT OR REPLACE INTO items VALUES(?,?,?,?,?,?)", (source, current.id, revision, current.digest, payload, time.time()))
                self.db.execute("INSERT INTO item_history VALUES(?,?,?,?,?)", (source, current.id, revision, payload, time.time()))
                for event in detector.detect(current, previous, revision):
                    decision = rules.decide(event)
                    self.db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?)", (event.id, source, current.id, event.event_type, event.fingerprint, canonical_json(asdict(event)), time.time()))
                    count += 1
                    identity = self.announcement_identity(event)
                    duplicate = False
                    if identity and (decision.notify or silent or historical):
                        existing = self.db.execute("SELECT event_id FROM announcement_claims WHERE identity=?", (identity,)).fetchone()
                        duplicate = existing is not None and existing[0] != event.id
                        if not existing:
                            self.db.execute("INSERT INTO announcement_claims VALUES(?,?,?)", (identity, event.id, time.time()))
                    if not silent and not historical and decision.notify and not duplicate:
                        status = "waiting_analysis" if decision.require_analysis else "pending"
                        self.db.execute("INSERT OR IGNORE INTO outbox(event_id,status) VALUES(?,?)", (event.id, status))
                        task = "change" if previous and event.event_type in ("content.changed", "change.uncertain") else "classification"
                        if settings.llm_enabled and (current.kind in ("article", "announcement", "unknown") or task == "change" or decision.require_analysis):
                            content = current.title + "\n" + current.content
                            if task == "change":
                                content = "ANTERIOR:\n" + (previous.title + "\n" + previous.content)[:settings.llm_max_input_chars // 2] + "\nACTUAL:\n" + content[:settings.llm_max_input_chars // 2]
                            content = content[:settings.llm_max_input_chars]
                            job_id = fingerprint({"source": source, "item": current.id, "revision": revision, "digest": current.digest, "task": task})
                            self.db.execute("INSERT OR IGNORE INTO analysis_jobs(id,source,item_id,digest,task,content,status,created) VALUES(?,?,?,?,?,?,?,?)", (job_id, source, current.id, current.digest, task, content, "pending", time.time()))
                            self.db.execute("INSERT OR REPLACE INTO event_jobs VALUES(?,?)", (event.id, job_id))
                        elif decision.require_analysis:
                            self.db.execute("UPDATE outbox SET status='dead',last_error='analysis_disabled' WHERE event_id=?", (event.id,))
            self.db.execute("UPDATE sources SET initialized=1,last_success=?,last_error=NULL,failures=0 WHERE id=?", (utcnow(), source))
            excess = self.db.execute("SELECT id FROM analysis_jobs WHERE status='pending' ORDER BY created DESC LIMIT -1 OFFSET ?", (settings.max_pending_analyses,)).fetchall()
            for row in excess:
                self.db.execute("UPDATE analysis_jobs SET status='superseded',content='' WHERE id=?", (row[0],))
                self.db.execute("UPDATE outbox SET status='dead',last_error='analysis_queue_full' WHERE status='waiting_analysis' AND event_id IN (SELECT event_id FROM event_jobs WHERE job_id=?)", (row[0],))
        return count

    def get_http_cache(self, url: str):
        row = self.db.execute("SELECT * FROM http_cache WHERE url=?", (url,)).fetchone()
        return dict(row) if row else None

    def set_http_cache(self, url: str, body: str, etag: str | None = None, last_modified: str | None = None):
        self.db.execute("INSERT OR REPLACE INTO http_cache VALUES(?,?,?,?,?)", (url, body, etag, last_modified, time.time()))
        # Cache is disposable transport data; source/item identities are kept separately.
        used = 0
        for position, row in enumerate(self.db.execute("SELECT url,length(CAST(body AS BLOB)) AS bytes FROM http_cache ORDER BY created DESC").fetchall()):
            used += row["bytes"]
            if position >= 128 or used > 32000000:
                self.db.execute("DELETE FROM http_cache WHERE url=?", (row["url"],))
        self.db.commit()

    def get_analysis_cache(self, key: str):
        row = self.db.execute("SELECT payload FROM analysis_cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_analysis_cache(self, key: str, result: dict):
        self.db.execute("INSERT OR REPLACE INTO analysis_cache VALUES(?,?,?)", (key, canonical_json(result), time.time()))
        self.db.commit()

    def due_analysis(self, limit: int):
        return self.db.execute("SELECT * FROM analysis_jobs WHERE status='pending' AND next_attempt<=? ORDER BY created DESC LIMIT ?", (time.time(), limit)).fetchall()

    def finish_analysis(self, job, result: dict | None, max_attempts: int):
        attempts = job["attempts"] + 1
        status = "done" if result is not None else ("failed" if attempts >= max_attempts else "pending")
        with self.transaction():
            self.db.execute("UPDATE analysis_jobs SET status=?,attempts=?,next_attempt=?,result=? WHERE id=?", (status, attempts, time.time() + min(3600, 60 * 2 ** attempts), canonical_json(result) if result else None, job["id"]))
            rows = self.db.execute("SELECT e.id,e.payload FROM events e JOIN event_jobs j ON j.event_id=e.id WHERE j.job_id=?", (job["id"],)).fetchall()
            for row in rows:
                if result is not None and row["payload"]:
                    payload = json.loads(row["payload"])
                    payload["analysis"] = {"engine": "model", "task": job["task"], "result": result, "verified": False}
                    self.db.execute("UPDATE events SET payload=? WHERE id=?", (canonical_json(payload), row["id"]))
                    self.db.execute("UPDATE outbox SET status='pending' WHERE event_id=? AND status='waiting_analysis'", (row["id"],))
                elif status == "failed":
                    self.db.execute("UPDATE outbox SET status='dead',last_error='analysis_failed' WHERE event_id=? AND status='waiting_analysis'", (row["id"],))

    def due_notifications(self, limit: int):
        rows = self.db.execute("SELECT e.payload,o.attempts FROM outbox o JOIN events e ON e.id=o.event_id WHERE o.status='pending' AND o.next_attempt<=? ORDER BY e.created LIMIT ?", (time.time(), limit)).fetchall()
        return [(Event(**json.loads(row[0])), row[1]) for row in rows]

    def notification_result(self, event_id: str, attempts: int, error: str | None = None, retry_after: float = 0, max_attempts: int = 12):
        status = "sent" if error is None else ("dead" if attempts >= max_attempts else "pending")
        with self.transaction():
            self.db.execute("UPDATE outbox SET status=?,attempts=?,next_attempt=?,last_error=?,delivered=? WHERE event_id=?", (status, attempts, time.time() + retry_after, error, time.time() if status == "sent" else None, event_id))
            self.db.execute("INSERT INTO notification_history(event_id,attempt,outcome,created) VALUES(?,?,?,?)", (event_id, attempts, error or "sent", time.time()))

    def stats(self):
        return {
            "sources": [dict(row) for row in self.db.execute("SELECT * FROM sources")],
            "notifications": [dict(row) for row in self.db.execute("SELECT status,count(*) AS count FROM outbox GROUP BY status")],
            "analyses": [dict(row) for row in self.db.execute("SELECT status,count(*) AS count FROM analysis_jobs GROUP BY status")],
            "recent_errors": [dict(row) for row in self.db.execute("SELECT component,code,detail,created FROM diagnostics ORDER BY id DESC LIMIT 20")],
        }

    def prune(self, retention_days: int):
        cutoff = time.time() - retention_days * 86400
        with self.transaction():
            for table in ("item_history", "analysis_cache", "notification_history", "diagnostics", "http_cache"):
                self.db.execute(f"DELETE FROM {table} WHERE created<?", (cutoff,))
            self.db.execute("UPDATE events SET payload=NULL WHERE created<? AND id NOT IN (SELECT event_id FROM outbox WHERE status IN ('pending','waiting_analysis')) AND id NOT IN (SELECT event_id FROM event_jobs JOIN analysis_jobs ON job_id=analysis_jobs.id WHERE analysis_jobs.status='pending')", (cutoff,))
            self.db.execute("UPDATE analysis_jobs SET content='',result=NULL WHERE created<? AND status!='pending'", (cutoff,))
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
