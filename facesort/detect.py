"""Bước 2: phát hiện mặt và embedding (đặc tả mục 5)."""

from __future__ import annotations

import logging
import sqlite3
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

from . import db
from .config import Config
from .imaging import ImageError, load_image, save_face_thumb

log = logging.getLogger("facesort.detect")


@dataclass
class Detection:
    x: float
    y: float
    w: float
    h: float
    score: float
    embedding: np.ndarray  # 512 float32, chuẩn hóa L2


class FaceEngine(Protocol):
    def detect(self, image: Image.Image) -> list[Detection]: ...


class InsightFaceEngine:
    """buffalo_l (SCRFD + ArcFace) chạy bằng onnxruntime trên CPU."""

    def __init__(self, det_size: int = 960):
        warnings.filterwarnings("ignore", category=FutureWarning)
        from insightface.app import FaceAnalysis

        self._app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
            allowed_modules=["detection", "recognition"],
        )
        self._app.prepare(ctx_id=-1, det_size=(det_size, det_size))

    def detect(self, image: Image.Image) -> list[Detection]:
        bgr = np.asarray(image)[:, :, ::-1].copy()  # RGB -> BGR
        out = []
        for f in self._app.get(bgr):
            x1, y1, x2, y2 = (float(v) for v in f.bbox)
            emb = np.asarray(f.normed_embedding, dtype=np.float32)
            out.append(Detection(x1, y1, x2 - x1, y2 - y1, float(f.det_score), emb))
        return out


def compute_quality(dets: list[Detection], config: Config) -> list[bool]:
    """quality_ok: đạt cả 3 ngưỡng (độ tin cậy, cỡ mặt, tỉ lệ so với mặt lớn nhất)."""
    if not dets:
        return []
    sides = [min(d.w, d.h) for d in dets]
    biggest = max(sides)
    return [
        d.score >= config.min_det_score
        and s >= config.min_face_px
        and s >= config.min_face_ratio * biggest
        for d, s in zip(dets, sides, strict=True)
    ]


@dataclass
class DetectSummary:
    done: int = 0
    errors: int = 0
    faces: int = 0


def run_detect(
    conn: sqlite3.Connection,
    config: Config,
    engine: FaceEngine,
    thumbs_dir: Path,
    progress: Callable[[int, int], None] | None = None,
) -> DetectSummary:
    input_dir = Path(config.input_dir)
    scan_id = db.current_scan_id(conn)
    # chỉ xử lý ảnh còn file trên đĩa; đọc từ đường dẫn còn sống nhỏ nhất
    pending = conn.execute(
        "SELECT p.sha256 AS sha256, MIN(f.rel_path) AS canonical_path FROM photos p "
        "JOIN files f ON f.sha256=p.sha256 AND f.last_seen_scan=? "
        "WHERE p.status IN ('pending', 'error') GROUP BY p.sha256 ORDER BY canonical_path",
        (scan_id,),
    ).fetchall()
    summary = DetectSummary()
    total = len(pending)
    for i, row in enumerate(pending, 1):
        sha, rel = row["sha256"], row["canonical_path"]
        try:
            img = load_image(input_dir / rel)
            dets = engine.detect(img)
            ok = compute_quality(dets, config)
            with conn:  # một transaction cho mỗi ảnh
                conn.execute("DELETE FROM faces WHERE photo_sha256=?", (sha,))
                for d, q in zip(dets, ok, strict=True):
                    cur = conn.execute(
                        "INSERT INTO faces (photo_sha256, x, y, w, h, det_score, embedding, "
                        "quality_ok) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (sha, d.x, d.y, d.w, d.h, d.score,
                         d.embedding.astype(np.float32).tobytes(), int(q)),
                    )
                    save_face_thumb(img, d.x, d.y, d.w, d.h, thumbs_dir / f"{cur.lastrowid}.jpg")
                conn.execute(
                    "UPDATE photos SET status='done', error=NULL, width=?, height=? WHERE sha256=?",
                    (img.width, img.height, sha),
                )
            summary.done += 1
            summary.faces += len(dets)
        except (ImageError, OSError) as e:
            log.warning("Ảnh lỗi %s: %s", rel, e)
            with conn:
                conn.execute(
                    "UPDATE photos SET status='error', error=? WHERE sha256=?", (str(e), sha)
                )
            summary.errors += 1
        if progress:
            progress(i, total)
    return summary
