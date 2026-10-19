"""SQLite-backed job state. One row per comic; panel progress lives in a JSON column."""
import json
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS comics (
    id      TEXT PRIMARY KEY,
    created REAL NOT NULL,
    source  TEXT NOT NULL,          -- 'web' or 'telegram'
    chat_id INTEGER,                -- Telegram chat, NULL for web
    status  TEXT NOT NULL,          -- queued | writing | drawing | done | failed
    error   TEXT,
    title   TEXT,
    panels  TEXT NOT NULL DEFAULT '[]'
)
"""

ACTIVE = ("queued", "writing", "drawing")


class Store:
    def __init__(self, path):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()  # one writer at a time; panel updates are read-modify-write
        with self._lock:
            self._db.execute(SCHEMA)
            self._db.commit()

    def create(self, comic_id, source, chat_id=None):
        with self._lock:
            self._db.execute(
                "INSERT INTO comics (id, created, source, chat_id, status) VALUES (?, ?, ?, ?, 'queued')",
                (comic_id, time.time(), source, chat_id),
            )
            self._db.commit()

    def update(self, comic_id, **fields):
        if "panels" in fields:
            fields["panels"] = json.dumps(fields["panels"])
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE comics SET {cols} WHERE id = ?", (*fields.values(), comic_id))
            self._db.commit()

    def set_panel(self, comic_id, index, **fields):
        with self._lock:
            row = self._db.execute("SELECT panels FROM comics WHERE id = ?", (comic_id,)).fetchone()
            panels = json.loads(row["panels"])
            panels[index].update(fields)
            self._db.execute("UPDATE comics SET panels = ? WHERE id = ?", (json.dumps(panels), comic_id))
            self._db.commit()

    def get(self, comic_id):
        with self._lock:
            row = self._db.execute("SELECT * FROM comics WHERE id = ?", (comic_id,)).fetchone()
        if row is None:
            return None
        comic = dict(row)
        comic["panels"] = json.loads(comic["panels"])
        return comic

    def active_for_chat(self, chat_id):
        with self._lock:
            row = self._db.execute(
                f"SELECT 1 FROM comics WHERE chat_id = ? AND status IN ({','.join('?' * len(ACTIVE))})",
                (chat_id, *ACTIVE),
            ).fetchone()
        return row is not None
