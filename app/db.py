import sqlite3, json, time
from contextlib import contextmanager
from .config import DB_PATH, DATA_DIR

def now_ts():
    return int(time.time())

@contextmanager
def db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            secret TEXT NOT NULL UNIQUE,
            limit_bytes INTEGER NOT NULL DEFAULT 0,
            used_bytes INTEGER NOT NULL DEFAULT 0,
            expire_at INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            sub_token TEXT NOT NULL UNIQUE,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            last_seen INTEGER NOT NULL DEFAULT 0,
            note TEXT DEFAULT ''
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            kind TEXT NOT NULL,
            message TEXT NOT NULL
        )
        """)
        # migrations
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        wanted = {
            "used_bytes": "INTEGER NOT NULL DEFAULT 0",
            "last_seen": "INTEGER NOT NULL DEFAULT 0",
            "note": "TEXT DEFAULT ''",
            "updated_at": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "INTEGER NOT NULL DEFAULT 0",
            "sub_token": "TEXT DEFAULT ''",
            "active": "INTEGER NOT NULL DEFAULT 1",
        }
        for col, typ in wanted.items():
            if col not in cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
        ts = now_ts()
        conn.execute("UPDATE users SET created_at=? WHERE created_at=0", (ts,))
        conn.execute("UPDATE users SET updated_at=? WHERE updated_at=0", (ts,))
        conn.execute("UPDATE users SET sub_token=lower(hex(randomblob(16))) WHERE sub_token='' OR sub_token IS NULL")

def setting_get(key, default=""):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

def setting_set(key, value):
    with db() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

def log(kind, message):
    with db() as conn:
        conn.execute("INSERT INTO events(ts,kind,message) VALUES(?,?,?)", (now_ts(), kind, message))
