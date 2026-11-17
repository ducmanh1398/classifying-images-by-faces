"""Bước 1: quét folder gốc, tính SHA-256 (đặc tả mục 5)."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from . import db
from .config import Config

CHUNK = 1024 * 1024
_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_SYSTEM = 0x4


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class ScanSummary:
    files: int = 0
    unique_photos: int = 0
    duplicate_files: int = 0
    hashed: int = 0
    missing: int = 0
    skipped_by_ext: Counter = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)


def _is_hidden(entry: os.DirEntry, st: os.stat_result) -> bool:
    if entry.name.startswith("."):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & (_FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM))


def _walk(
    root: Path, skip_dir: Path | None, errors: list[str]
) -> Iterator[tuple[str, os.DirEntry, os.stat_result]]:
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError as e:
            errors.append(f"{cur}: {e}")
            continue
        with it:
            entries = sorted(it, key=lambda e: e.name)
        for entry in entries:
            try:
                st = entry.stat()
                if _is_hidden(entry, st):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if skip_dir is not None and Path(entry.path).resolve() == skip_dir:
                        continue
                    stack.append(Path(entry.path))
                elif entry.is_file():
                    rel = Path(entry.path).relative_to(root).as_posix()
                    yield rel, entry, st
            except OSError as e:
                errors.append(f"{entry.path}: {e}")


def scan(
    conn: sqlite3.Connection,
    config: Config,
    hasher: Callable[[Path], str] = sha256_file,
    progress: Callable[[int], None] | None = None,
) -> ScanSummary:
    root = Path(config.input_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Không tìm thấy folder ảnh gốc: {root}")
    skip_dir = Path(config.output_dir).resolve()
    exts = config.ext_set
    summary = ScanSummary()
    scan_id = db.current_scan_id(conn) + 1

    known = {
        r["rel_path"]: r for r in conn.execute("SELECT rel_path, size, mtime_ns, sha256 FROM files")
    }
    for rel, entry, st in _walk(root, skip_dir, summary.errors):
        if entry.name.lower() == "desktop.ini":
            continue
        ext = os.path.splitext(entry.name)[1].lower().lstrip(".")
        if ext not in exts:
            summary.skipped_by_ext[ext or "(không đuôi)"] += 1
            continue
        old = known.get(rel)
        if old and old["size"] == st.st_size and old["mtime_ns"] == st.st_mtime_ns:
            sha = old["sha256"]
        else:
            try:
                sha = hasher(Path(entry.path))
            except OSError as e:
                summary.errors.append(f"{rel}: {e}")
                continue
            summary.hashed += 1
        conn.execute(
            "INSERT INTO files (rel_path, size, mtime_ns, sha256, last_seen_scan) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(rel_path) DO UPDATE SET "
            "size=excluded.size, mtime_ns=excluded.mtime_ns, sha256=excluded.sha256, "
            "last_seen_scan=excluded.last_seen_scan",
            (rel, st.st_size, st.st_mtime_ns, sha, scan_id),
        )
        summary.files += 1
        if progress:
            progress(summary.files)

    conn.execute(
        "INSERT OR IGNORE INTO photos (sha256, canonical_path, status) "
        "SELECT sha256, MIN(rel_path), 'pending' FROM files WHERE last_seen_scan=? "
        "GROUP BY sha256",
        (scan_id,),
    )
    conn.execute(
        "UPDATE photos SET canonical_path = (SELECT MIN(rel_path) FROM files "
        "WHERE files.sha256=photos.sha256 AND last_seen_scan=?) "
        "WHERE EXISTS (SELECT 1 FROM files WHERE files.sha256=photos.sha256 "
        "AND last_seen_scan=?)",
        (scan_id, scan_id),
    )
    summary.missing = conn.execute(
        "SELECT COUNT(*) FROM files WHERE last_seen_scan<?", (scan_id,)
    ).fetchone()[0]
    summary.unique_photos = conn.execute(
        "SELECT COUNT(DISTINCT sha256) FROM files WHERE last_seen_scan=?", (scan_id,)
    ).fetchone()[0]
    summary.duplicate_files = summary.files - summary.unique_photos
    db.set_meta(conn, "scan_id", str(scan_id))
    conn.commit()
    return summary
