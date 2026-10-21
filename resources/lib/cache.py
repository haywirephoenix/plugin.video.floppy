"""Small SQLite key/value cache with per-entry expiry, shared by plugin and service.

Each process keeps one connection (WAL mode, so widgets running side by side read while
another writes). Two more tables let widgets hand work to the service: ``widget_keys``
lists the Floppy requests widgets made recently, so the service keeps them fresh, and
``tmdb_pending`` holds artwork a widget could not wait for.
"""

import json
import os
import sqlite3
import threading
import time

from . import common, perf

_LOCK = threading.Lock()
_DB_NAME = "cache.db"
_conn = None

# Expired entries stay this long so widgets can show them while the service refreshes.
STALE_MAX = 7 * 24 * 3600
# A widget key is written again at most this often when it is only being read.
_TOUCH_EVERY = 600


def _connect():
    global _conn
    if _conn is not None:
        return _conn
    path = os.path.join(common.ensure_profile_dir(), _DB_NAME)
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache ("
        " key TEXT PRIMARY KEY,"
        " expires REAL NOT NULL,"
        " value TEXT NOT NULL)"
    )
    # Checked rather than caught: under Kodi a sub-interpreter's sqlite3.OperationalError can be a
    # different class from the one raised, so "except" missed it and the service never connected.
    if "stored" not in {row[1] for row in conn.execute("PRAGMA table_info(cache)")}:
        conn.execute("ALTER TABLE cache ADD COLUMN stored REAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS widget_keys ("
        " key TEXT PRIMARY KEY,"
        " path TEXT NOT NULL,"
        " params TEXT NOT NULL,"
        " ttl REAL NOT NULL,"
        " last_used REAL NOT NULL,"
        " last_try REAL NOT NULL DEFAULT 0)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tmdb_pending ("
        " kind TEXT NOT NULL,"
        " tmdb_id TEXT NOT NULL,"
        " queued REAL NOT NULL,"
        " PRIMARY KEY (kind, tmdb_id))"
    )
    conn.commit()
    _conn = conn
    return conn


def _stored_time(stored, expires, ttl):
    # Rows written before the stored column existed: work it out from the expiry.
    return stored if stored is not None else expires - ttl


def get(key, ttl=0, not_before=0):
    """Cached value, or None if missing, expired, or stored before ``not_before``."""
    entry = get_entry(key)
    if not entry:
        return None
    stored, expires, value = entry
    if expires < time.time():
        return None
    if not_before and _stored_time(stored, expires, ttl) < not_before:
        return None
    try:
        return json.loads(value)
    except ValueError:
        return None


def get_entry(key):
    """(stored, expires, raw JSON) for a key, expired or not, or None."""
    with _LOCK, perf.span("sqlite_get"):
        return _connect().execute(
            "SELECT stored, expires, value FROM cache WHERE key = ?", (key,)
        ).fetchone()


def get_many(keys):
    """{key: value} for the keys that are cached and not expired, in as few queries as possible."""
    keys = list(keys)
    found = {}
    now = time.time()
    with _LOCK, perf.span("sqlite_get_many"):
        conn = _connect()
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            rows = conn.execute(
                "SELECT key, value FROM cache WHERE expires >= ? AND key IN ({})".format(
                    ",".join("?" * len(chunk))),
                [now] + chunk,
            ).fetchall()
            for key, value in rows:
                try:
                    found[key] = json.loads(value)
                except ValueError:
                    pass
    return found


def set(key, value, ttl_seconds):  # noqa: A001 - mirrors dict-like API
    if ttl_seconds <= 0:
        return
    payload = json.dumps(value)
    now = time.time()
    with _LOCK, perf.span("sqlite_set"):
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, expires, value, stored) VALUES (?, ?, ?, ?)",
            (key, now + ttl_seconds, payload, now),
        )
        conn.commit()


def delete_prefix(prefix):
    with _LOCK:
        conn = _connect()
        conn.execute("DELETE FROM cache WHERE key LIKE ?", (prefix + "%",))
        conn.commit()


def purge_expired():
    now = time.time()
    with _LOCK:
        conn = _connect()
        conn.execute("DELETE FROM cache WHERE expires < ?", (now - STALE_MAX,))
        conn.execute("DELETE FROM widget_keys WHERE last_used < ?", (now - STALE_MAX,))
        conn.execute("DELETE FROM tmdb_pending WHERE queued < ?", (now - 24 * 3600,))
        conn.commit()


def clear_all():
    with _LOCK:
        conn = _connect()
        conn.execute("DELETE FROM cache")
        conn.execute("DELETE FROM tmdb_pending")
        conn.commit()
        conn.execute("VACUUM")


# -- work handed from widgets to the service ----------------------------------------

def track_widget_key(key, path, params, ttl):
    """Remember that a widget asked for this Floppy request, so the service keeps it fresh."""
    now = time.time()
    with _LOCK, perf.span("sqlite_track"):
        conn = _connect()
        row = conn.execute("SELECT last_used FROM widget_keys WHERE key = ?", (key,)).fetchone()
        if row and row[0] > now - _TOUCH_EVERY:
            return
        conn.execute(
            "INSERT OR REPLACE INTO widget_keys (key, path, params, ttl, last_used)"
            " VALUES (?, ?, ?, ?, ?)",
            (key, path, json.dumps(params, sort_keys=True), ttl, now),
        )
        conn.commit()


def widget_keys(used_since):
    """Widget requests used since ``used_since``, with their cache state.

    Rows are (key, path, params, ttl, last_try, stored, expires); stored/expires are None
    when nothing is cached.
    """
    with _LOCK:
        rows = _connect().execute(
            "SELECT w.key, w.path, w.params, w.ttl, w.last_try, c.stored, c.expires"
            " FROM widget_keys w LEFT JOIN cache c ON c.key = w.key"
            " WHERE w.last_used >= ?",
            (used_since,),
        ).fetchall()
    result = []
    for key, path, params, ttl, last_try, stored, expires in rows:
        if expires is not None:
            stored = _stored_time(stored, expires, ttl)
        try:
            params = json.loads(params)
        except ValueError:
            params = {}
        result.append((key, path, params, ttl, last_try, stored, expires))
    return result


def mark_tried(key):
    with _LOCK:
        conn = _connect()
        conn.execute("UPDATE widget_keys SET last_try = ? WHERE key = ?", (time.time(), key))
        conn.commit()


def queue_tmdb(pairs):
    """Artwork lookups a widget did not wait for; the service fetches them."""
    pairs = list(pairs)
    if not pairs:
        return
    now = time.time()
    with _LOCK, perf.span("sqlite_queue"):
        conn = _connect()
        conn.executemany(
            "INSERT OR IGNORE INTO tmdb_pending (kind, tmdb_id, queued) VALUES (?, ?, ?)",
            [(kind, str(tmdb_id), now) for kind, tmdb_id in pairs],
        )
        conn.commit()


def pending_tmdb(limit=100):
    with _LOCK:
        return _connect().execute(
            "SELECT kind, tmdb_id FROM tmdb_pending ORDER BY queued LIMIT ?", (limit,)
        ).fetchall()


def done_tmdb(pairs):
    with _LOCK:
        conn = _connect()
        conn.executemany("DELETE FROM tmdb_pending WHERE kind = ? AND tmdb_id = ?",
                         [(kind, str(tmdb_id)) for kind, tmdb_id in pairs])
        conn.commit()
