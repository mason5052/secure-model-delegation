from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def identifier() -> str:
    return uuid.uuid4().hex


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class Store:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(data_dir / "application.sqlite3", check_same_thread=False)
        if os.name != "nt":
            os.chmod(data_dir / "application.sqlite3", 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS policies (
                id TEXT PRIMARY KEY, text TEXT NOT NULL, rules_json TEXT NOT NULL,
                created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL,
                status TEXT NOT NULL, destination TEXT NOT NULL, policy_id TEXT NOT NULL,
                model TEXT, model_digest TEXT, route TEXT, external_attempted INTEGER DEFAULT 0,
                request_hash TEXT NOT NULL, outbound_hash TEXT, error_code TEXT,
                content_json TEXT);
        """)
        if "reviewed" not in {row[1] for row in self.db.execute("PRAGMA table_info(policies)")}:
            self.db.execute("ALTER TABLE policies ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 0")
            self.db.execute("UPDATE policies SET reviewed=1 WHERE active=1")
        self.db.execute("""UPDATE runs SET status=CASE WHEN external_attempted=1
            THEN 'delivery_unknown' ELSE 'interrupted' END, error_code='application_stopped'
            WHERE status='running'""")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def settings(self) -> dict:
        row = self.db.execute("SELECT value FROM settings WHERE key='save_content'").fetchone()
        return {"save_content": bool(json.loads(row[0])) if row else False}

    def set_content_retention(self, enabled: bool) -> dict:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('save_content', ?)", (json.dumps(enabled),))
        return self.settings()

    def add_policy(self, text: str, compiled: dict, active: bool = False) -> dict:
        policy_id = identifier()
        with self.db:
            if active:
                self.db.execute("UPDATE policies SET active=0")
            self.db.execute("INSERT INTO policies (id,text,rules_json,created_at,active,reviewed) VALUES (?, ?, ?, ?, ?, ?)",
                            (policy_id, text, json.dumps(compiled), timestamp(), int(active), int(active)))
        return self.policy(policy_id)

    def policy(self, policy_id: str | None = None) -> dict | None:
        row = self.db.execute("SELECT * FROM policies WHERE id=?" if policy_id else
                              "SELECT * FROM policies WHERE active=1", (policy_id,) if policy_id else ()).fetchone()
        if not row:
            return None
        compiled = json.loads(row["rules_json"])
        return {**compiled, "id": row["id"], "text": row["text"],
                "active": bool(row["active"]), "created_at": row["created_at"]}

    def activate(self, policy_id: str) -> dict:
        if self.policy(policy_id) is None:
            raise KeyError(policy_id)
        with self.db:
            self.db.execute("UPDATE policies SET active=0")
            self.db.execute("UPDATE policies SET active=1,reviewed=1 WHERE id=?", (policy_id,))
        return self.policy(policy_id)

    def latest_draft(self) -> dict | None:
        row = self.db.execute("SELECT id FROM policies WHERE active=0 AND reviewed=0 ORDER BY created_at DESC LIMIT 1").fetchone()
        return self.policy(row[0]) if row else None

    def update_draft(self, policy_id: str, compiled: dict) -> dict:
        with self.db:
            self.db.execute("UPDATE policies SET rules_json=? WHERE id=? AND active=0",
                            (json.dumps(compiled), policy_id))
        return self.policy(policy_id)

    def begin_run(self, run_id: str, conversation_id: str, destination: str,
                  policy_id: str, model: dict, messages: list) -> None:
        with self.db:
            self.db.execute("""INSERT INTO runs
                (id,conversation_id,created_at,status,destination,policy_id,model,model_digest,request_hash)
                VALUES (?,?,?,'running',?,?,?,?,?)""",
                (run_id, conversation_id, timestamp(), destination, policy_id,
                 model.get("model"), model.get("model_digest"), digest(messages)))

    def finish_run(self, run_id: str, result: dict, messages: list, save_content: bool) -> None:
        content = json.dumps({"messages": messages, "result": result}, ensure_ascii=False) if save_content else None
        with self.db:
            self.db.execute("""UPDATE runs SET status='completed',route=?,external_attempted=?,
                outbound_hash=?,content_json=? WHERE id=?""",
                (result.get("route"), int(result.get("external_attempted", False)),
                 digest(result["payload"]) if result.get("payload") is not None else None, content, run_id))

    def mark_dispatched(self, run_id: str, payload: list) -> None:
        with self.db:
            self.db.execute("UPDATE runs SET external_attempted=1,outbound_hash=? WHERE id=?", (digest(payload), run_id))

    def fail_run(self, run_id: str, code: str, attempted: bool, delivery_unknown: bool = False) -> None:
        with self.db:
            self.db.execute("UPDATE runs SET status=?,error_code=?,external_attempted=? WHERE id=?",
                            ("delivery_unknown" if delivery_unknown else "failed", code, int(attempted), run_id))

    def activity(self) -> list[dict]:
        rows = self.db.execute("""SELECT id,conversation_id,created_at,status,destination,policy_id,
            model,model_digest,route,external_attempted,request_hash,outbound_hash,error_code,
            (content_json IS NOT NULL) AS has_content FROM runs ORDER BY created_at DESC LIMIT 200""").fetchall()
        return [dict(row) for row in rows]

    def run(self, run_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        raw = result.pop("content_json")
        result["has_content"] = raw is not None
        result["content"] = json.loads(raw) if raw else None
        return result

    def clear_activity(self) -> None:
        with self.db:
            self.db.execute("DELETE FROM runs")
        # Reclaim deleted optional body content rather than retaining it in free pages.
        self.db.execute("VACUUM")
