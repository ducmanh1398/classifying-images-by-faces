"""Trang kiểm tra tĩnh: mỗi cụm một hàng thumbnail (đặc tả kế hoạch 3.7)."""

from __future__ import annotations

import html
import sqlite3
from pathlib import Path

MAX_PER_ROW = 40
MAX_NOISE = 300


def _row(title: str, face_ids: list[int], limit: int) -> str:
    imgs = "".join(
        f'<img src="thumbs/faces/{i}.jpg" title="mặt {i}" loading="lazy">'
        for i in face_ids[:limit]
    )
    more = f"<span> +{len(face_ids) - limit}</span>" if len(face_ids) > limit else ""
    return f"<section><h3>{html.escape(title)}</h3><div>{imgs}{more}</div></section>"


def build_contact_sheet(conn: sqlite3.Connection, dest: Path) -> Path:
    """Ghi HTML vào thư mục dự án (dest) để đường dẫn thumbs/ là tương đối."""
    parts = []
    clusters = conn.execute(
        "SELECT c.id, COUNT(f.id) AS n FROM clusters c JOIN faces f ON f.cluster_id=c.id "
        "GROUP BY c.id ORDER BY n DESC"
    ).fetchall()
    for c in clusters:
        ids = [
            r[0]
            for r in conn.execute(
                "SELECT id FROM faces WHERE cluster_id=? ORDER BY det_score DESC", (c["id"],)
            )
        ]
        parts.append(_row(f"Cụm {c['id']} — {c['n']} mặt", ids, MAX_PER_ROW))
    noise = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM faces WHERE cluster_id IS NULL AND quality_ok=1 AND ignored=0 "
            "ORDER BY det_score DESC"
        )
    ]
    parts.append(_row(f"Mặt nhiễu — {len(noise)} mặt", noise, MAX_NOISE))
    body = "\n".join(parts)
    doc = (
        '<!doctype html><html lang="vi"><meta charset="utf-8"><title>Kiểm tra cụm</title>'
        "<style>body{font-family:sans-serif;margin:16px}section{margin-bottom:18px}"
        "img{width:80px;height:80px;object-fit:cover;margin:2px;border-radius:4px}</style>"
        f"<h1>Kiểm tra cụm khuôn mặt ({len(clusters)} cụm)</h1>{body}</html>"
    )
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "contact_sheet.html"
    out.write_text(doc, encoding="utf-8")
    return out
