"""Thao tác gắn nhãn kèm nhật ký để hoàn tác 1 bước (UI_PLAN G2)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from . import labels as lb
from .errors import FacesortError

MAX_LOG = 100


def _snapshot(conn: sqlite3.Connection, cluster_ids=(), face_ids=()) -> dict:
    snap: dict = {"clusters": {}, "faces": {}}
    for cid in cluster_ids:
        r = conn.execute("SELECT label_id, ignored FROM clusters WHERE id=?", (cid,)).fetchone()
        if r is None:
            raise FacesortError("Không tìm thấy nhóm.")
        snap["clusters"][str(cid)] = dict(r)
    for fid in face_ids:
        r = conn.execute(
            "SELECT cluster_id, label_id, ignored, detached FROM faces WHERE id=?", (fid,)
        ).fetchone()
        if r is None:
            raise FacesortError("Không tìm thấy khuôn mặt.")
        snap["faces"][str(fid)] = dict(r)
    return snap


def _log(conn: sqlite3.Connection, kind: str, snap: dict, created_labels=()) -> None:
    snap["created_labels"] = list(created_labels)
    conn.execute(
        "INSERT INTO ops_log (kind, payload, created_at) VALUES (?, ?, ?)",
        (kind, json.dumps(snap), datetime.now(UTC).isoformat(timespec="seconds")),
    )
    conn.execute(
        "DELETE FROM ops_log WHERE id NOT IN (SELECT id FROM ops_log ORDER BY id DESC LIMIT ?)",
        (MAX_LOG,),
    )


def _label(conn: sqlite3.Connection, name: str, unlabeled_folder: str) -> tuple[int, list[int]]:
    existing = lb.find_label(conn, name)
    lid = lb.get_or_create_label(conn, name, unlabeled_folder)
    return lid, ([] if existing else [lid])


def label_cluster(
    conn: sqlite3.Connection, cluster_id: int, name: str, unlabeled_folder: str
) -> int:
    """Gắn nhãn cho nhóm; tên trùng nhãn có sẵn thì dùng chung nhãn đó (gộp)."""
    snap = _snapshot(conn, [cluster_id])
    lid, created = _label(conn, name, unlabeled_folder)
    conn.execute("UPDATE clusters SET label_id=?, ignored=0 WHERE id=?", (lid, cluster_id))
    _log(conn, "label_cluster", snap, created)
    conn.commit()
    return lid


def ignore_cluster(conn: sqlite3.Connection, cluster_id: int, ignored: bool = True) -> None:
    snap = _snapshot(conn, [cluster_id])
    if ignored:
        conn.execute("UPDATE clusters SET ignored=1, label_id=NULL WHERE id=?", (cluster_id,))
    else:
        conn.execute("UPDATE clusters SET ignored=0 WHERE id=?", (cluster_id,))
    _log(conn, "ignore_cluster", snap)
    conn.commit()


def detach_face(conn: sqlite3.Connection, face_id: int) -> None:
    """Tách mặt khỏi nhóm; mặt này không bị tự gán lại về nhóm có nhãn."""
    snap = _snapshot(conn, face_ids=[face_id])
    conn.execute(
        "UPDATE faces SET cluster_id=NULL, detached=1, label_id=NULL WHERE id=?", (face_id,)
    )
    _log(conn, "detach_face", snap)
    conn.commit()


def label_face(conn: sqlite3.Connection, face_id: int, name: str, unlabeled_folder: str) -> int:
    """Gán tay nhãn cho riêng một mặt (luôn thắng nhãn của nhóm, R5)."""
    snap = _snapshot(conn, face_ids=[face_id])
    lid, created = _label(conn, name, unlabeled_folder)
    conn.execute("UPDATE faces SET label_id=?, ignored=0 WHERE id=?", (lid, face_id))
    _log(conn, "label_face", snap, created)
    conn.commit()
    return lid


def ignore_face(conn: sqlite3.Connection, face_id: int, ignored: bool = True) -> None:
    snap = _snapshot(conn, face_ids=[face_id])
    conn.execute("UPDATE faces SET ignored=?, label_id=NULL WHERE id=?", (int(ignored), face_id))
    _log(conn, "ignore_face", snap)
    conn.commit()


def undo(conn: sqlite3.Connection) -> str | None:
    """Hoàn tác thao tác gần nhất; trả về loại thao tác hoặc None nếu không có gì."""
    row = conn.execute("SELECT id, kind, payload FROM ops_log ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    snap = json.loads(row["payload"])
    for cid, v in snap["clusters"].items():
        conn.execute(
            "UPDATE clusters SET label_id=?, ignored=? WHERE id=?",
            (v["label_id"], v["ignored"], int(cid)),
        )
    for fid, v in snap["faces"].items():
        conn.execute(
            "UPDATE faces SET cluster_id=?, label_id=?, ignored=?, detached=? WHERE id=?",
            (v["cluster_id"], v["label_id"], v["ignored"], v["detached"], int(fid)),
        )
    for lid in snap.get("created_labels", []):
        used = conn.execute(
            "SELECT (SELECT COUNT(*) FROM clusters WHERE label_id=?) "
            "+ (SELECT COUNT(*) FROM faces WHERE label_id=?) "
            "+ (SELECT COUNT(*) FROM exports WHERE label_id=?)",
            (lid, lid, lid),
        ).fetchone()[0]
        if not used:
            conn.execute("DELETE FROM labels WHERE id=?", (lid,))
    conn.execute("DELETE FROM ops_log WHERE id=?", (row["id"],))
    conn.commit()
    return row["kind"]
