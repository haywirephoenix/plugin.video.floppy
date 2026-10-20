"""Small SQLite key/value cache with per-entry expiry, shared by plugin and service."""

import json
import os
import sqlite3
import threading
import time

from . import common

_LOCK = threading.Lock()
_DB_NAME = "cache.db"


def _connect():
    path = os.path.join(common.ensure_profile_dir(), _DB_NAME)
    conn = sqlite3.connect(path, timeout=10)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache ("
        " key TEXT PRIMARY KEY,"
        " expires REAL NOT NULL,"
        " value TEXT NOT NULL)"
    )
    return conn


def get(key):
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT expires, value FROM cache WHERE key = ?", (key,)
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return None
    expires, value = row
    if expires < time.time():
        return None
    try:
        return json.loads(value)
    except ValueError:
        return None


def set(key, value, ttl_seconds):  # noqa: A001 - mirrors dict-like API
    if ttl_seconds <= 0:
        return
    payload = json.dumps(value)
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, expires, value) VALUES (?, ?, ?)",
                (key, time.time() + ttl_seconds, payload),
            )
            conn.commit()
        finally:
            conn.close()


def delete_prefix(prefix):
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("DELETE FROM cache WHERE key LIKE ?", (prefix + "%",))
            conn.commit()
        finally:
            conn.close()


def purge_expired():
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("DELETE FROM cache WHERE expires < ?", (time.time(),))
            conn.commit()
        finally:
            conn.close()


def clear_all():
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("DELETE FROM cache")
            conn.commit()
            conn.execute("VACUUM")
        finally:
            conn.close()
