"""Bước 3: gom cụm khuôn mặt (đặc tả mục 5). Lần chạy đầu; gán tăng dần ở giai đoạn 5."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np

from .config import Config
from .errors import FacesortError


@dataclass
class ClusterSummary:
    clusters: int
    clustered_faces: int
    noise_faces: int


def load_embeddings(conn: sqlite3.Connection) -> tuple[list[int], np.ndarray]:
    rows = conn.execute(
        "SELECT id, embedding FROM faces WHERE quality_ok=1 AND ignored=0 "
        "AND embedding IS NOT NULL ORDER BY id"
    ).fetchall()
    ids = [r["id"] for r in rows]
    if not rows:
        return ids, np.zeros((0, 512), dtype=np.float32)
    return ids, np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])


def dbscan_cosine(
    emb: np.ndarray, eps: float, min_samples: int, chunk: int = 2048
) -> np.ndarray:
    """DBSCAN thuần numpy trên khoảng cách cosine (vector đã chuẩn hóa L2).

    Tự viết vì scikit-learn bị chính sách Application Control của máy chặn một DLL
    (xem DECISIONS.md). Nhãn -1 là nhiễu.
    """
    n = len(emb)
    labels = np.full(n, -1, dtype=np.int64)
    if n == 0:
        return labels
    neigh: list[np.ndarray] = []
    for start in range(0, n, chunk):
        dist = 1.0 - emb[start : start + chunk] @ emb.T
        neigh.extend(np.flatnonzero(row <= eps) for row in dist)
    core = np.array([len(x) >= min_samples for x in neigh])
    cluster = 0
    for i in range(n):
        if labels[i] != -1 or not core[i]:
            continue
        labels[i] = cluster
        stack = [i]
        while stack:
            j = stack.pop()
            if not core[j]:
                continue
            for k in neigh[j]:
                if labels[k] == -1:
                    labels[k] = cluster
                    stack.append(k)
        cluster += 1
    return labels


def cluster_first_run(conn: sqlite3.Connection, config: Config) -> ClusterSummary:
    has_labels = conn.execute(
        "SELECT (SELECT COUNT(*) FROM clusters WHERE label_id IS NOT NULL) "
        "+ (SELECT COUNT(*) FROM faces WHERE label_id IS NOT NULL OR ignored=1) "
        "+ (SELECT COUNT(*) FROM clusters WHERE ignored=1)"
    ).fetchone()[0]
    if has_labels:
        raise FacesortError(
            "Đã có nhãn trong dự án; gom cụm tăng dần chưa được hỗ trợ ở phiên bản này."
        )
    ids, emb = load_embeddings(conn)
    with conn:
        conn.execute("UPDATE faces SET cluster_id=NULL")
        conn.execute("DELETE FROM clusters")
        if not ids:
            return ClusterSummary(0, 0, 0)
        labels = dbscan_cosine(emb, config.cluster_eps, config.cluster_min_samples)
        # cụm lớn nhất có id nhỏ nhất
        order = sorted(set(labels) - {-1}, key=lambda c: -int((labels == c).sum()))
        for c in order:
            cid = conn.execute("INSERT INTO clusters (label_id) VALUES (NULL)").lastrowid
            members = [(cid, ids[i]) for i in np.flatnonzero(labels == c)]
            conn.executemany("UPDATE faces SET cluster_id=? WHERE id=?", members)
    noise = int((labels == -1).sum())
    return ClusterSummary(len(order), len(ids) - noise, noise)
