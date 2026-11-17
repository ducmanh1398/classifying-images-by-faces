"""SQLite: schema, migration, truy vấn cơ bản (đặc tả mục 4)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_V1 = """
CREATE TABLE files (
    rel_path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    last_seen_scan INTEGER NOT NULL
);
CREATE INDEX idx_files_sha ON files(sha256);

CREATE TABLE photos (
    sha256 TEXT PRIMARY KEY,
    canonical_path TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'error')),
    error TEXT
);

CREATE TABLE labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    folder_name TEXT NOT NULL UNIQUE
);

CREATE TABLE clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label_id INTEGER REFERENCES labels(id),
    ignored INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE faces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_sha256 TEXT NOT NULL REFERENCES photos(sha256),
    x REAL NOT NULL,
    y REAL NOT NULL,
    w REAL NOT NULL,
    h REAL NOT NULL,
    det_score REAL NOT NULL,
    embedding BLOB,
    quality_ok INTEGER NOT NULL DEFAULT 0,
    cluster_id INTEGER REFERENCES clusters(id),
    label_id INTEGER REFERENCES labels(id),
    ignored INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_faces_photo ON faces(photo_sha256);
CREATE INDEX idx_faces_cluster ON faces(cluster_id);

-- label_id = 0 dành cho thư mục "không nhãn" (_Khac).
-- size và mtime_ns của file đích để dùng lại SHA-256 mà không cần băm lại.
CREATE TABLE exports (
    label_id INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    dest_rel_path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    exported_at TEXT NOT NULL,
    PRIMARY KEY (label_id, sha256)
);

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# v2: cờ "đã tách khỏi cụm" (không tự gán lại) và nhật ký thao tác gắn nhãn để hoàn tác
SCHEMA_V2 = """
ALTER TABLE faces ADD COLUMN detached INTEGER NOT NULL DEFAULT 0;
CREATE TABLE ops_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# phiên bản -> script SQL nâng cấp lên phiên bản đó
MIGRATIONS: dict[int, str] = {1: SCHEMA_V1, 2: SCHEMA_V2}
LATEST = max(MIGRATIONS)


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if row is None:
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def migrate(conn: sqlite3.Connection, target: int = LATEST) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    version = current_version(conn)
    for v in sorted(MIGRATIONS):
        if version < v <= target:
            conn.executescript("BEGIN;\n" + MIGRATIONS[v])
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (v,))
            conn.commit()


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def current_scan_id(conn: sqlite3.Connection) -> int:
    return int(get_meta(conn, "scan_id", "0") or 0)


def status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    scan_id = current_scan_id(conn)
    return {
        "files": conn.execute(
            "SELECT COUNT(*) FROM files WHERE last_seen_scan=?", (scan_id,)
        ).fetchone()[0],
        "photos": one("SELECT COUNT(*) FROM photos"),
        "photos_pending": one("SELECT COUNT(*) FROM photos WHERE status='pending'"),
        "photos_done": one("SELECT COUNT(*) FROM photos WHERE status='done'"),
        "photos_error": one("SELECT COUNT(*) FROM photos WHERE status='error'"),
        "faces": one("SELECT COUNT(*) FROM faces"),
        "clusters": one("SELECT COUNT(*) FROM clusters"),
        "clusters_labeled": one("SELECT COUNT(*) FROM clusters WHERE label_id IS NOT NULL"),
        "labels": one("SELECT COUNT(*) FROM labels"),
    }
