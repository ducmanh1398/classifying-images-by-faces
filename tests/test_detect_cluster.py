import numpy as np
import pytest
from PIL import Image

from facesort.cluster import cluster_run as cluster_first_run
from facesort.config import Config
from facesort.detect import compute_quality, run_detect
from tests.factories import World
from tests.fakes import FakeFaceEngine, det, unit


def real_photos(w, n):
    """Ảnh JPG thật trên đĩa, đăng ký bằng scan."""
    from facesort.scan import scan

    for i in range(n):
        Image.new("RGB", (300, 200), (i * 20, 5, 5)).save(w.input_dir / f"{i:02d}.jpg")
    scan(w.conn, w.config)


def test_quality_thresholds():
    cfg = Config(input_dir="a", output_dir="b")
    dets = [det(size=200), det(size=40), det(size=40 + 40, score=0.3), det(size=40)]
    # min_face_px=60 -> 200 ok; 40 loại; 80 nhưng score thấp loại; ratio 0.25*200=50
    assert compute_quality(dets, cfg) == [True, False, False, False]
    dets2 = [det(size=400), det(size=80)]  # 80 < 0.25*400=100 -> loại (người hậu cảnh)
    assert compute_quality(dets2, cfg) == [True, False]
    assert compute_quality([], cfg) == []


def test_detect_stores_faces_thumbs_and_status(tmp_path):
    w = World(tmp_path)
    real_photos(w, 2)
    eng = FakeFaceEngine([[det(), det(x=150)], []])
    thumbs = tmp_path / "thumbs"
    s = run_detect(w.conn, w.config, eng, thumbs)
    assert (s.done, s.errors, s.faces) == (2, 0, 2)
    assert w.conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0] == 2
    assert len(list(thumbs.glob("*.jpg"))) == 2
    assert w.conn.execute("SELECT COUNT(*) FROM photos WHERE status='done'").fetchone()[0] == 2
    blob = w.conn.execute("SELECT embedding FROM faces").fetchone()[0]
    assert len(blob) == 512 * 4


def test_interrupt_then_resume_processes_rest_only(tmp_path):
    w = World(tmp_path)
    real_photos(w, 4)
    eng = FakeFaceEngine([[det()], [det()], KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        run_detect(w.conn, w.config, eng, tmp_path / "t")
    assert w.conn.execute("SELECT COUNT(*) FROM photos WHERE status='done'").fetchone()[0] == 2
    eng2 = FakeFaceEngine([[det()], [det()]])
    run_detect(w.conn, w.config, eng2, tmp_path / "t")
    assert eng2.calls == 2
    assert w.conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0] == 4


def test_corrupt_photo_does_not_stop_batch_and_is_retried(tmp_path):
    w = World(tmp_path)
    real_photos(w, 3)
    (w.input_dir / "01.jpg").write_bytes(b"broken")
    from facesort.scan import scan

    scan(w.conn, w.config)
    eng = FakeFaceEngine([[det()], [det()]])
    s = run_detect(w.conn, w.config, eng, tmp_path / "t")
    assert (s.done, s.errors) == (2, 1)
    row = w.conn.execute("SELECT error FROM photos WHERE status='error'").fetchone()
    assert row["error"]
    # sửa file, lần sau thử lại
    Image.new("RGB", (50, 50)).save(w.input_dir / "01.jpg")
    scan(w.conn, w.config)
    s = run_detect(w.conn, w.config, FakeFaceEngine([[det()]]), tmp_path / "t")
    assert s.done == 1


def _centers(k, dim=512, seed=1):
    rng = np.random.default_rng(seed)
    return [unit(rng.normal(size=dim)) for _ in range(k)]


def _add_points(w, centers, per=8, noise=0.02, extra_noise=3):
    rng = np.random.default_rng(2)
    sha = w.add_photo("p.png", 1)
    for c in centers:
        for _ in range(per):
            e = unit(c + rng.normal(scale=noise / np.sqrt(512) * 5, size=512))
            _insert(w, sha, e)
    for _ in range(extra_noise):
        _insert(w, sha, unit(rng.normal(size=512)))


def _insert(w, sha, emb, quality_ok=1):
    w.conn.execute(
        "INSERT INTO faces (photo_sha256,x,y,w,h,det_score,embedding,quality_ok) "
        "VALUES (?,0,0,100,100,.9,?,?)",
        (sha, emb.astype(np.float32).tobytes(), quality_ok),
    )
    w.conn.commit()


def test_cluster_five_groups_plus_noise(tmp_path):
    w = World(tmp_path)
    _add_points(w, _centers(5))
    s = cluster_first_run(w.conn, w.config)
    assert s.clusters == 5
    assert s.noise_faces == 3
    n_null = w.conn.execute("SELECT COUNT(*) FROM faces WHERE cluster_id IS NULL").fetchone()[0]
    assert n_null == 3
    sizes = [r[0] for r in w.conn.execute(
        "SELECT COUNT(*) FROM faces WHERE cluster_id IS NOT NULL GROUP BY cluster_id")]
    assert sizes == [8] * 5


def test_cluster_ignores_low_quality(tmp_path):
    w = World(tmp_path)
    sha = w.add_photo("p.png", 1)
    c = _centers(1)[0]
    for _ in range(5):
        _insert(w, sha, c, quality_ok=0)
    assert cluster_first_run(w.conn, w.config).clusters == 0


def test_cluster_rerun_resets_when_no_labels(tmp_path):
    w = World(tmp_path)
    _add_points(w, _centers(2))
    cluster_first_run(w.conn, w.config)
    cluster_first_run(w.conn, w.config)
    assert w.conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0] == 2


def test_dbscan_matches_expected_noise_and_border():
    from facesort.cluster import dbscan_cosine

    a = unit([1, 0, 0])
    emb = np.vstack([a, unit([1, 0.05, 0]), unit([1, -0.05, 0]), unit([0, 1, 0])])
    lab = dbscan_cosine(emb, eps=0.05, min_samples=3)
    assert list(lab) == [0, 0, 0, -1]
    assert list(dbscan_cosine(emb, eps=0.05, min_samples=5)) == [-1] * 4
    assert len(dbscan_cosine(np.zeros((0, 3), dtype=np.float32), 0.5, 3)) == 0


def test_contact_sheet(tmp_path):
    from facesort.debug import build_contact_sheet

    w = World(tmp_path)
    _add_points(w, _centers(2))
    cluster_first_run(w.conn, w.config)
    out = build_contact_sheet(w.conn, tmp_path / "proj")
    text = out.read_text(encoding="utf-8")
    assert text.count("<section>") == 3  # 2 cụm + nhiễu
    assert "Mặt nhiễu" in text
