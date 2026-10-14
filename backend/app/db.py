"""SQLite storage (WAL). One connection per call keeps threads (API + worker)
independent; writes are short so WAL handles the concurrency."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS api_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    prefix TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    last_used_at INTEGER
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    api_key_enc TEXT NOT NULL,
    chat_model TEXT NOT NULL DEFAULT '',
    video_model TEXT NOT NULL DEFAULT '',
    tts_model TEXT NOT NULL DEFAULT '',
    tts_voice TEXT NOT NULL DEFAULT '',
    clip_seconds INTEGER NOT NULL DEFAULT 5,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE SET NULL,
    title TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    preset TEXT NOT NULL DEFAULT 'tiktok',
    target_seconds INTEGER NOT NULL DEFAULT 30,
    language TEXT NOT NULL DEFAULT 'id-ID',
    options_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS scenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    visual_prompt TEXT NOT NULL,
    narration TEXT NOT NULL DEFAULT '',
    duration REAL NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    clip_status TEXT NOT NULL DEFAULT 'pending',
    clip_file TEXT,
    clip_error TEXT,
    clip_version INTEGER NOT NULL DEFAULT 0,
    narration_file TEXT,
    narration_json TEXT,
    continues INTEGER NOT NULL DEFAULT 0,
    clip_gen_seconds REAL,
    clip_attempts INTEGER,
    UNIQUE(project_id, idx)
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, id);
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id, updated_at);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive column migrations for databases created by older versions."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(scenes)")}
    if "continues" not in columns:  # scene continues the previous shot (same place & moment)
        conn.execute("ALTER TABLE scenes ADD COLUMN continues INTEGER NOT NULL DEFAULT 0")
    if "clip_gen_seconds" not in columns:  # wall time to generate the current clip (incl. retries)
        conn.execute("ALTER TABLE scenes ADD COLUMN clip_gen_seconds REAL")
    if "clip_attempts" not in columns:
        conn.execute("ALTER TABLE scenes ADD COLUMN clip_attempts INTEGER")


_OPEN_CLOSE_LOCK = threading.Lock()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            _migrate(conn)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # Opening and closing are serialized: some SQLite builds (seen with 3.51.1)
        # deadlock in the unix VFS when one thread opens a connection while another
        # closes the last WAL connection. Queries themselves still run concurrently.
        with _OPEN_CLOSE_LOCK:
            conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            with _OPEN_CLOSE_LOCK:
                conn.close()

    def one(self, sql: str, params: tuple = ()) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Run a write; returns ``lastrowid`` (inserts) or ``rowcount``."""
        with self.connect() as conn:
            cur = conn.execute(sql, params)
            return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def now() -> int:
    return int(time.time())


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(raw: str | None, default: Any = None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default
