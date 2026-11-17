"""G1.1–1.3: mặt đại diện, gợi ý gộp, gán tăng dần."""

import numpy as np

from facesort.cluster import cluster_run, representatives, suggest_merges
from tests.factories import World
from tests.fakes import unit


def centers(k, seed=1):
    rng = np.random.default_rng(seed)
    return [unit(rng.normal(size=512)) for _ in range(k)]


def jitter(c, rng, s=0.015):
    return unit(c + rng.normal(scale=s, size=512))


def insert(w, sha, emb, cluster=None, det=0.9, size=100, quality=1):
    cur = w.conn.execute(
        "INSERT INTO faces (photo_sha256,x,y,w,h,det_score,embedding,quality_ok,cluster_id) "
        "VALUES (?,0,0,?,?,?,?,?,?)",
        (sha, size, size, det, emb.astype(np.float32).tobytes(), quality, cluster),
    )
    w.conn.commit()
    return cur.lastrowid


def test_representatives_main_closest_to_centroid_and_diverse(tmp_path):
    w = World(tmp_path)
    sha = w.add_photo("p.png", 1)
    rng = np.random.default_rng(3)
    base = centers(1)[0]
    # 3 nhóm con quanh một người
    subs = [jitter(base, rng, 0.05) for _ in range(3)]
    cid = w.cluster()
    ids = {}
    for si, sc in enumerate(subs):
        for j in range(6):
            ids[(si, j)] = insert(w, sha, jitter(sc, rng, 0.005), cluster=cid)
    main, small = representatives(w.conn, cid, k=6)
    assert main is not None and main not in small
    assert len(small) == 6 and len(set(small)) == 6
    groups = {k[0] for k, v in ids.items() if v in small}
    assert groups == {0, 1, 2}  # đủ mọi nhóm con


def test_representatives_main_prefers_clear_large_face(tmp_path):
    w = World(tmp_path)
    sha = w.add_photo("p.png", 1)
    rng = np.random.default_rng(4)
    c = centers(1)[0]
    cid = w.cluster()
    for _ in range(5):
        insert(w, sha, jitter(c, rng), cluster=cid, det=0.6, size=70)
    best = insert(w, sha, jitter(c, rng), cluster=cid, det=0.99, size=300)
    main, _ = representatives(w.conn, cid)
    assert main == best


def test_representatives_small_cluster_and_empty(tmp_path):
    w = World(tmp_path)
    sha = w.add_photo("p.png", 1)
    cid = w.cluster()
    assert representatives(w.conn, cid) == (None, [])
    f = insert(w, sha, centers(1)[0], cluster=cid)
    assert representatives(w.conn, cid) == (f, [])


def test_suggest_merges_same_person_not_other(tmp_path):
    w = World(tmp_path)
    sha = w.add_photo("p.png", 1)
    rng = np.random.default_rng(5)
    a, b = centers(2)
    a_side = unit(a + 0.5 * b)  # cùng người nhưng góc mặt khác (còn gần)
    c1, c2, c3 = w.cluster("Lan"), w.cluster(), w.cluster()
    for _ in range(4):
        insert(w, sha, jitter(a, rng), cluster=c1)
        insert(w, sha, jitter(a_side, rng), cluster=c2)
        insert(w, sha, jitter(b, rng), cluster=c3)
    # a_side cách a: cos = 1/sqrt(1.25)... dùng ngưỡng 0.6 mặc định
    got = suggest_merges(w.conn, c1)
    ids = [g["cluster_id"] for g in got]
    assert c2 in ids
    assert c3 not in ids or got[0]["cluster_id"] == c2
    assert got[0]["cluster_id"] == c2


def test_suggest_merges_skips_ignored_and_same_label(tmp_path):
    w = World(tmp_path)
    sha = w.add_photo("p.png", 1)
    rng = np.random.default_rng(6)
    a = centers(1)[0]
    c1, c2, c3 = w.cluster("Lan"), w.cluster("Lan"), w.cluster(ignored=True)
    for c in (c1, c2, c3):
        for _ in range(3):
            insert(w, sha, jitter(a, rng), cluster=c)
    assert suggest_merges(w.conn, c1) == []


def _four_people(w, rng, per=6):
    sha = w.add_photo("p.png", 1)
    cs = centers(4)
    for c in cs:
        for _ in range(per):
            insert(w, sha, jitter(c, rng), quality=1)
    return sha, cs


def test_incremental_keeps_labels_and_assigns_new_faces(tmp_path):
    w = World(tmp_path)
    rng = np.random.default_rng(7)
    sha, cs = _four_people(w, rng)
    first = cluster_run(w.conn, w.config)
    assert first.clusters == 4 and first.assigned == 0
    # gắn nhãn cho người 0
    f0 = w.conn.execute("SELECT id FROM faces ORDER BY id LIMIT 1").fetchone()[0]
    cid0 = w.conn.execute("SELECT cluster_id FROM faces WHERE id=?", (f0,)).fetchone()[0]
    w.conn.execute("UPDATE clusters SET label_id=? WHERE id=?", (w.label("Lan"), cid0))
    w.conn.commit()
    # thêm: 3 mặt mới của người 0, 5 mặt của người mới (người 5)
    new_person = centers(1, seed=99)[0]
    sha2 = w.add_photo("q.png", 2)
    for _ in range(3):
        insert(w, sha2, jitter(cs[0], rng))
    for _ in range(5):
        insert(w, sha2, jitter(new_person, rng))
    s = cluster_run(w.conn, w.config)
    assert s.assigned == 3
    assert s.new_clusters == 4  # 3 nhóm chưa nhãn gom lại + 1 người mới
    assert s.clusters == 5
    # nhãn Lan còn nguyên, cụm cũ không đổi id, có 6+3 mặt
    n = w.conn.execute("SELECT COUNT(*) FROM faces WHERE cluster_id=?", (cid0,)).fetchone()[0]
    assert n == 9
    assert w.conn.execute("SELECT label_id FROM clusters WHERE id=?", (cid0,)).fetchone()[0]
    assert w.conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 1
    unl = w.conn.execute("SELECT COUNT(*) FROM clusters WHERE label_id IS NULL").fetchone()[0]
    assert unl == 4  # 3 nhóm chưa nhãn cũ (gom lại) + 1 người mới


def test_incremental_manual_label_and_detached_untouched(tmp_path):
    w = World(tmp_path)
    rng = np.random.default_rng(8)
    sha, cs = _four_people(w, rng)
    cluster_run(w.conn, w.config)
    f0 = w.conn.execute("SELECT id, cluster_id FROM faces ORDER BY id LIMIT 1").fetchone()
    cid0 = f0["cluster_id"]
    w.conn.execute("UPDATE clusters SET label_id=? WHERE id=?", (w.label("Lan"), cid0))
    manual = insert(w, sha, jitter(cs[0], rng))
    w.conn.execute("UPDATE faces SET label_id=? WHERE id=?", (w.label("Bà B"), manual))
    detached = insert(w, sha, jitter(cs[0], rng))
    w.conn.execute("UPDATE faces SET detached=1 WHERE id=?", (detached,))
    w.conn.commit()
    cluster_run(w.conn, w.config)
    r = w.conn.execute("SELECT cluster_id, label_id FROM faces WHERE id=?", (manual,)).fetchone()
    assert r["cluster_id"] is None and r["label_id"] is not None
    d = w.conn.execute("SELECT cluster_id FROM faces WHERE id=?", (detached,)).fetchone()[0]
    assert d != cid0  # không tự gán lại về nhóm đã có nhãn


def test_incremental_ignored_cluster_absorbs_lookalikes(tmp_path):
    w = World(tmp_path)
    rng = np.random.default_rng(9)
    sha, cs = _four_people(w, rng)
    cluster_run(w.conn, w.config)
    cid = w.conn.execute("SELECT cluster_id FROM faces ORDER BY id LIMIT 1").fetchone()[0]
    w.conn.execute("UPDATE clusters SET ignored=1 WHERE id=?", (cid,))
    w.conn.commit()
    newf = insert(w, sha, jitter(cs[0], rng))
    cluster_run(w.conn, w.config)
    assert w.conn.execute("SELECT cluster_id FROM faces WHERE id=?", (newf,)).fetchone()[0] == cid


def test_incremental_idempotent(tmp_path):
    w = World(tmp_path)
    rng = np.random.default_rng(10)
    _four_people(w, rng)
    cluster_run(w.conn, w.config)
    cid = w.conn.execute("SELECT cluster_id FROM faces ORDER BY id LIMIT 1").fetchone()[0]
    w.conn.execute("UPDATE clusters SET label_id=? WHERE id=?", (w.label("Lan"), cid))
    w.conn.commit()
    before = [tuple(r) for r in w.conn.execute("SELECT id, cluster_id FROM faces ORDER BY id")]
    s = cluster_run(w.conn, w.config)
    after = [tuple(r) for r in w.conn.execute("SELECT id, cluster_id FROM faces ORDER BY id")]
    assert s.assigned == 0 and s.clusters == 4
    # nhóm có nhãn giữ nguyên; thành viên giữ nguyên
    assert [b for b in before if b[1] == cid] == [a for a in after if a[1] == cid]
