"""Bước 3: gom cụm, gán tăng dần, mặt đại diện, gợi ý gộp (đặc tả mục 5, UI_PLAN mục 4)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np

from .config import Config

SUGGEST_MERGE_DISTANCE = 0.6


@dataclass
class ClusterSummary:
    clusters: int
    clustered_faces: int
    noise_faces: int
    assigned: int = 0  # mặt tự gán vào nhóm đã có nhãn hoặc đã bỏ qua
    new_clusters: int = 0


def _vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def load_embeddings(conn: sqlite3.Connection) -> tuple[list[int], np.ndarray]:
    rows = conn.execute(
        "SELECT id, embedding FROM faces WHERE quality_ok=1 AND ignored=0 "
        "AND embedding IS NOT NULL ORDER BY id"
    ).fetchall()
    ids = [r["id"] for r in rows]
    if not rows:
        return ids, np.zeros((0, 512), dtype=np.float32)
    return ids, np.vstack([_vec(r["embedding"]) for r in rows])


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


def cluster_run(conn: sqlite3.Connection, config: Config) -> ClusterSummary:
    """Gom cụm; giữ nhãn đã gắn (đặc tả mục 5, bước 3).

    1. Nhóm đã có nhãn hoặc đã bỏ qua, và mặt đã gán tay: giữ nguyên.
    2. Mặt còn lại gần nhất một mặt thuộc nhóm đã có nhãn/bỏ qua trong
       `assign_threshold`: vào nhóm đó. Mặt đã bị "tách" không tự gán lại.
    3. Phần còn lại, cùng các nhóm chưa gắn nhãn cũ: gom lại từ đầu bằng DBSCAN.
    Lần đầu (chưa có nhãn) chỉ chạy bước 3.
    """
    rows = conn.execute(
        "SELECT f.id, f.embedding, f.cluster_id, f.label_id, f.detached, "
        "c.label_id AS c_label, c.ignored AS c_ignored FROM faces f "
        "LEFT JOIN clusters c ON c.id=f.cluster_id "
        "WHERE f.quality_ok=1 AND f.ignored=0 AND f.embedding IS NOT NULL ORDER BY f.id"
    ).fetchall()

    ref_idx, free_idx = [], []
    for i, r in enumerate(rows):
        fixed_cluster = r["cluster_id"] is not None and (r["c_label"] is not None or r["c_ignored"])
        if r["label_id"] is not None:
            continue  # gán tay: không đụng vào
        (ref_idx if fixed_cluster else free_idx).append(i)

    emb = np.vstack([_vec(r["embedding"]) for r in rows]) if rows else np.zeros((0, 512), "f4")
    assigned: dict[int, int] = {}  # face_id -> cluster_id
    if ref_idx and free_idx:
        refs = emb[ref_idx]
        ref_cluster = [rows[i]["cluster_id"] for i in ref_idx]
        cand = [i for i in free_idx if not rows[i]["detached"]]
        for s in range(0, len(cand), 2048):
            part = cand[s : s + 2048]
            dist = 1.0 - emb[part] @ refs.T
            best = dist.argmin(axis=1)
            for local, (row_i, b) in enumerate(zip(part, best, strict=True)):
                if dist[local, b] < config.assign_threshold:
                    assigned[rows[row_i]["id"]] = ref_cluster[b]

    remaining = [i for i in free_idx if rows[i]["id"] not in assigned]
    with conn:
        # xóa nhóm chưa gắn nhãn cũ; mặt gán tay trong đó chỉ mất liên kết nhóm
        old = [
            r[0]
            for r in conn.execute("SELECT id FROM clusters WHERE label_id IS NULL AND ignored=0")
        ]
        for chunk_start in range(0, len(old), 500):
            ph = ",".join("?" * len(old[chunk_start : chunk_start + 500]))
            conn.execute(
                f"UPDATE faces SET cluster_id=NULL WHERE cluster_id IN ({ph})",
                old[chunk_start : chunk_start + 500],
            )
            conn.execute(
                f"DELETE FROM clusters WHERE id IN ({ph})", old[chunk_start : chunk_start + 500]
            )
        conn.executemany(
            "UPDATE faces SET cluster_id=? WHERE id=?", [(c, f) for f, c in assigned.items()]
        )
        new_clusters = 0
        noise = len(remaining)
        if remaining:
            labels = dbscan_cosine(
                emb[remaining], config.cluster_eps, config.cluster_min_samples
            )
            order = sorted(set(labels) - {-1}, key=lambda c: -int((labels == c).sum()))
            for c in order:
                cid = conn.execute("INSERT INTO clusters (label_id) VALUES (NULL)").lastrowid
                members = [(cid, rows[remaining[i]]["id"]) for i in np.flatnonzero(labels == c)]
                conn.executemany("UPDATE faces SET cluster_id=? WHERE id=?", members)
            new_clusters = len(order)
            noise = int((labels == -1).sum())
    total_clusters = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
    clustered = conn.execute(
        "SELECT COUNT(*) FROM faces WHERE cluster_id IS NOT NULL AND quality_ok=1"
    ).fetchone()[0]
    return ClusterSummary(total_clusters, clustered, noise, len(assigned), new_clusters)


# tên cũ, giữ cho tương thích
cluster_first_run = cluster_run


# ---------------------------------------------------------------- đại diện, gợi ý


def representatives(
    conn: sqlite3.Connection, cluster_id: int, k: int = 6
) -> tuple[int | None, list[int]]:
    """1 mặt lớn đại diện (gần tâm, rõ, to) và k mặt khác nhau nhất (farthest-point)."""
    rows = conn.execute(
        "SELECT id, embedding, det_score, w, h FROM faces WHERE cluster_id=? "
        "AND embedding IS NOT NULL ORDER BY id",
        (cluster_id,),
    ).fetchall()
    if not rows:
        return None, []
    emb = np.vstack([_vec(r["embedding"]) for r in rows])
    centroid = emb.mean(axis=0)
    centroid /= np.linalg.norm(centroid) or 1.0
    sim = emb @ centroid
    det = np.array([r["det_score"] for r in rows])
    size = np.minimum([min(r["w"], r["h"]) / 200.0 for r in rows], 1.0)
    main = int(np.argmax(sim + 0.3 * det + 0.2 * size))
    chosen = [main]
    mind = 1.0 - emb @ emb[main]
    mind[main] = -1.0
    while len(chosen) <= k and (mind > 0).any():
        nxt = int(np.argmax(mind))
        chosen.append(nxt)
        mind = np.minimum(mind, 1.0 - emb @ emb[nxt])
        mind[chosen] = -1.0
    return rows[main]["id"], [rows[i]["id"] for i in chosen[1:]]


def cluster_centroids(conn: sqlite3.Connection) -> dict[int, tuple[np.ndarray, int]]:
    sums: dict[int, np.ndarray] = {}
    counts: dict[int, int] = {}
    for r in conn.execute(
        "SELECT cluster_id, embedding FROM faces WHERE cluster_id IS NOT NULL "
        "AND embedding IS NOT NULL AND quality_ok=1 AND ignored=0"
    ):
        v = _vec(r["embedding"])
        cid = r["cluster_id"]
        if cid in sums:
            sums[cid] += v
            counts[cid] += 1
        else:
            sums[cid] = v.copy()
            counts[cid] = 1
    return {c: (s / (np.linalg.norm(s) or 1.0), counts[c]) for c, s in sums.items()}


def suggest_merges(
    conn: sqlite3.Connection,
    cluster_id: int,
    threshold: float = SUGGEST_MERGE_DISTANCE,
    limit: int = 3,
    centroids: dict[int, tuple[np.ndarray, int]] | None = None,
) -> list[dict]:
    """Các nhóm khác có thể cùng một người (tâm gần nhau), bỏ qua nhóm đã bỏ qua hoặc cùng nhãn."""
    cents = centroids if centroids is not None else cluster_centroids(conn)
    if cluster_id not in cents:
        return []
    info = {
        r["id"]: (r["label_id"], r["ignored"], r["name"])
        for r in conn.execute(
            "SELECT c.id, c.label_id, c.ignored, l.name FROM clusters c "
            "LEFT JOIN labels l ON l.id=c.label_id"
        )
    }
    me = info.get(cluster_id)
    if me is None:
        return []
    out = []
    for cid, (c, n) in cents.items():
        if cid == cluster_id or cid not in info:
            continue
        label_id, ignored, name = info[cid]
        if ignored or (me[0] is not None and label_id == me[0]):
            continue
        d = float(1.0 - cents[cluster_id][0] @ c)
        if d <= threshold:
            out.append({"cluster_id": cid, "distance": d, "faces": n, "label": name})
    out.sort(key=lambda x: x["distance"])
    return out[:limit]
