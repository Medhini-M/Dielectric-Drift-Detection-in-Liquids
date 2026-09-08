"""
Thin SQLite access layer.

Uses a single shared connection with check_same_thread=False because the
demo generator runs on a background thread and Flask handles requests on
its own thread(s). SQLite serializes writes internally; for this prototype's
write volume (roughly one insert every 1-2 seconds) that's sufficient.
"""

import os
import sqlite3
import threading

from config import DATABASE_PATH, SCHEMA_PATH

_lock = threading.Lock()
_connection = None


def get_connection():
    global _connection
    if _connection is None:
        os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
        _connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
    return _connection


def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    conn = get_connection()
    with open(SCHEMA_PATH, "r") as f:
        schema = f.read()
    with _lock:
        conn.executescript(schema)
        conn.commit()


def execute_write(sql, params=()):
    conn = get_connection()
    with _lock:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid


def execute_read(sql, params=()):
    conn = get_connection()
    with _lock:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def execute_read_one(sql, params=()):
    rows = execute_read(sql, params)
    return rows[0] if rows else None


def get_app_state(key, default=None):
    row = execute_read_one("SELECT value FROM app_state WHERE key = ?", (key,))
    return row["value"] if row else default


def set_app_state(key, value):
    execute_write(
        "INSERT INTO app_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
