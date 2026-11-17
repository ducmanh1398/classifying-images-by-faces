"""Chuẩn hóa tên nhãn, tên thư mục, thao tác nhãn trong DB (đặc tả mục 4, 7)."""

from __future__ import annotations

import re
import sqlite3
import unicodedata

from .errors import LabelError

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"}
_RESERVED |= {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def normalize(name: str) -> str:
    """NFC, cắt khoảng trắng hai đầu, gộp khoảng trắng liên tiếp."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", name)).strip()


def name_key(name: str) -> str:
    return unicodedata.normalize("NFC", normalize(name).casefold())


def folder_name_for(name: str) -> str:
    folder = _FORBIDDEN.sub("_", normalize(name)).rstrip(". ")
    if folder.split(".")[0].upper() in _RESERVED:
        folder += "_"
    return folder


def validate(name: str, unlabeled_folder: str) -> tuple[str, str, str]:
    """Trả về (name, name_key, folder_name) hoặc ném LabelError."""
    clean = normalize(name)
    if not clean:
        raise LabelError("Tên nhãn không được để trống.")
    key = name_key(clean)
    folder = folder_name_for(clean)
    if not folder:
        raise LabelError(f"Tên nhãn không hợp lệ: {name!r}")
    unlabeled = unlabeled_folder.casefold()
    if key == unlabeled or folder.casefold() == unlabeled:
        raise LabelError(f"Tên nhãn trùng với thư mục dành riêng '{unlabeled_folder}'.")
    return clean, key, folder


def _unique_folder(conn: sqlite3.Connection, folder: str, exclude_id: int | None = None) -> str:
    taken = {
        r["folder_name"].casefold()
        for r in conn.execute("SELECT id, folder_name FROM labels")
        if r["id"] != exclude_id
    }
    candidate, n = folder, 1
    while candidate.casefold() in taken:
        n += 1
        candidate = f"{folder} ({n})"
    return candidate


def find_label(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute("SELECT id FROM labels WHERE name_key=?", (name_key(name),)).fetchone()
    return row["id"] if row else None


def get_or_create_label(conn: sqlite3.Connection, name: str, unlabeled_folder: str) -> int:
    clean, key, folder = validate(name, unlabeled_folder)
    row = conn.execute("SELECT id FROM labels WHERE name_key=?", (key,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO labels (name, name_key, folder_name) VALUES (?, ?, ?)",
        (clean, key, _unique_folder(conn, folder)),
    )
    conn.commit()
    return cur.lastrowid


def merge_labels(conn: sqlite3.Connection, src_id: int, dst_id: int) -> None:
    """Chuyển mọi cụm và mặt gán tay từ src sang dst rồi xóa src."""
    if src_id == dst_id:
        return
    conn.execute("UPDATE clusters SET label_id=? WHERE label_id=?", (dst_id, src_id))
    conn.execute("UPDATE faces SET label_id=? WHERE label_id=?", (dst_id, src_id))
    # chuyển sổ xuất sang nhãn đích; dòng trùng SHA-256 ở lại (nhãn mồ côi) để
    # export dọn bản copy thừa trên đĩa
    conn.execute("UPDATE OR IGNORE exports SET label_id=? WHERE label_id=?", (dst_id, src_id))
    conn.execute("DELETE FROM labels WHERE id=?", (src_id,))
    conn.commit()


def rename_label(
    conn: sqlite3.Connection, label_id: int, new_name: str, unlabeled_folder: str
) -> int:
    """Đổi tên nhãn. Nếu trùng nhãn khác thì gộp; trả về id nhãn còn lại."""
    clean, key, folder = validate(new_name, unlabeled_folder)
    other = conn.execute(
        "SELECT id FROM labels WHERE name_key=? AND id<>?", (key, label_id)
    ).fetchone()
    if other:
        merge_labels(conn, label_id, other["id"])
        return other["id"]
    conn.execute(
        "UPDATE labels SET name=?, name_key=?, folder_name=? WHERE id=?",
        (clean, key, _unique_folder(conn, folder, exclude_id=label_id), label_id),
    )
    conn.commit()
    return label_id


def effective_label_id(
    face_ignored: bool,
    face_label: int | None,
    cluster_ignored: bool | None,
    cluster_label: int | None,
) -> int | None:
    """Nhãn hiệu lực của một khuôn mặt (đặc tả mục 4, 3 bước)."""
    if face_ignored or cluster_ignored:
        return None
    if face_label is not None:
        return face_label
    return cluster_label
