"""G1.4-1.6 và thao tác gắn nhãn / hoàn tác."""

import numpy as np
import pytest
from PIL import Image

from facesort import labels, ops
from facesort.errors import FacesortError
from facesort.export import ensure_disk_space, reconcile_exports, run_export
from facesort.pipeline import export_full, scan_all
from tests.factories import World
from tests.fakes import FakeFaceEngine, det, unit

_counter = {"n": 0}


def make_jpgs(w, names):
    for n in names:
        _counter["n"] += 1
        k = _counter["n"]
        Image.new("RGB", (100 + k, 80), (k * 3 % 256, 5, 5)).save(w.input_dir / n)  # cỡ khác nhau


def embs(k, seed=1):
    rng = np.random.default_rng(seed)
    return [unit(rng.normal(size=512)) for _ in range(k)]


def faces_for(centers):
    rng = np.random.default_rng(0)
    return [det(emb=unit(c + rng.normal(scale=0.01, size=512))) for c in centers]


def fresh(tmp_path):
    w = World(tmp_path)
    w.conn.execute("DELETE FROM meta")
    w.conn.commit()
    return w


# ---------------------------------------------------------------- 1.4


def test_export_twice_second_copies_nothing(tmp_path):
    w = fresh(tmp_path)
    names = [f"{i:02d}.jpg" for i in range(8)]
    make_jpgs(w, names)
    eng = FakeFaceEngine([faces_for(embs(1)) for _ in names])
    r = export_full(w.conn, w.config, tmp_path / "th", lambda: eng)
    assert r.preview.total_files == 8  # chưa có nhãn nên vào _Khac
    assert len(list((w.output_dir / "_Khac").iterdir())) == 8
    r2 = export_full(w.conn, w.config, tmp_path / "th", lambda: eng)
    assert r2.preview.total_files == 0
    assert eng.calls == 8  # lần hai không detect lại


def test_scan_all_cancel_midway_db_consistent(tmp_path):
    w = fresh(tmp_path)
    make_jpgs(w, [f"{i}.jpg" for i in range(6)])
    eng = FakeFaceEngine([faces_for(embs(1)) for _ in range(6)])
    n = {"i": 0}

    def stop():
        n["i"] += 1
        return n["i"] > 5

    r = scan_all(w.conn, w.config, tmp_path / "th", lambda: eng, should_stop=stop)
    assert r.cancelled and r.cluster is None
    done = w.conn.execute("SELECT COUNT(*) FROM photos WHERE status='done'").fetchone()[0]
    assert 0 < done < 6
    assert w.conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0] == done
    eng2 = FakeFaceEngine([faces_for(embs(1)) for _ in range(6 - done)])
    r2 = scan_all(w.conn, w.config, tmp_path / "th", lambda: eng2)
    assert not r2.cancelled and eng2.calls == 6 - done


def test_scan_all_skips_model_when_nothing_pending(tmp_path):
    w = fresh(tmp_path)
    make_jpgs(w, ["a.jpg"])
    eng = FakeFaceEngine([faces_for(embs(1))])
    scan_all(w.conn, w.config, tmp_path / "th", lambda: eng)

    def boom():
        raise AssertionError("không được nạp model")

    scan_all(w.conn, w.config, tmp_path / "th", boom)


def test_new_photo_flow_assigns_to_labeled_person(tmp_path):
    w = fresh(tmp_path)
    people = embs(2)
    make_jpgs(w, [f"a{i}.jpg" for i in range(4)])
    eng = FakeFaceEngine([faces_for([people[0]]) for _ in range(4)])
    scan_all(w.conn, w.config, tmp_path / "th", lambda: eng)
    cid = w.conn.execute("SELECT id FROM clusters").fetchone()[0]
    ops.label_cluster(w.conn, cid, "Lan", "_Khac")
    export_full(w.conn, w.config, tmp_path / "th", lambda: eng)
    assert len(list((w.output_dir / "Lan").iterdir())) == 4
    make_jpgs(w, ["new1.jpg", "new2.jpg"])
    eng2 = FakeFaceEngine([faces_for([people[0]]), faces_for([people[1]])])
    r = export_full(w.conn, w.config, tmp_path / "th", lambda: eng2)
    assert r.scan_all.cluster.assigned == 1
    assert len(list((w.output_dir / "Lan").iterdir())) == 5
    assert r.preview.total_files == 2  # 1 vào Lan, 1 vào _Khac


# ---------------------------------------------------------------- 1.5


def _exported_world(tmp_path):
    w = World(tmp_path)
    s1, s2 = w.add_photo("a.png", 1), w.add_photo("b.png", 2)
    c1 = w.cluster("Lan")
    w.face(s1, cluster=c1)
    w.face(s2, cluster=c1)
    run_export(w.conn, w.config)
    return w, c1


def test_rename_after_export_moves_folder(tmp_path):
    w, _ = _exported_world(tmp_path)
    lid = labels.find_label(w.conn, "Lan")
    labels.rename_label(w.conn, lid, "Cô Lan", "_Khac")
    preview, _rows = run_export(w.conn, w.config)
    assert w.folder_files("Cô Lan") == ["a.png", "b.png"]
    assert not (w.output_dir / "Lan").exists()
    assert preview.total_files == 0
    paths = [r[0] for r in w.conn.execute("SELECT dest_rel_path FROM exports")]
    assert sorted(paths) == ["Cô Lan/a.png", "Cô Lan/b.png"]


def test_case_only_rename(tmp_path):
    w, _ = _exported_world(tmp_path)
    lid = labels.find_label(w.conn, "Lan")
    labels.rename_label(w.conn, lid, "LAN", "_Khac")
    run_export(w.conn, w.config)
    assert w.folder_files("LAN") == ["a.png", "b.png"]


def test_merge_after_export_moves_files_dedups(tmp_path):
    w = World(tmp_path)
    s1, s2, s3 = (w.add_photo(f"{n}.png", i) for i, n in enumerate("abc", 1))
    ca, cb = w.cluster("Lan"), w.cluster("Lan Anh")
    w.face(s1, cluster=ca)
    w.face(s2, cluster=cb)
    w.face(s3, cluster=ca)
    w.face(s3, cluster=cb)  # ảnh c có cả hai nhãn
    run_export(w.conn, w.config)
    assert w.folder_files("Lan") == ["a.png", "c.png"]
    assert w.folder_files("Lan Anh") == ["b.png", "c.png"]
    lid_b = labels.find_label(w.conn, "Lan Anh")
    labels.rename_label(w.conn, lid_b, "lan", "_Khac")  # trùng "Lan" nên gộp
    preview, _rows = run_export(w.conn, w.config)
    assert w.folder_files("Lan") == ["a.png", "b.png", "c.png"]
    assert not (w.output_dir / "Lan Anh").exists()
    assert preview.total_files == 0
    assert w.plan().actions == []


def test_reconcile_never_touches_user_files(tmp_path):
    w, _ = _exported_world(tmp_path)
    (w.output_dir / "Lan" / "ghi_chu.txt").write_text("của tôi", encoding="utf-8")
    lid = labels.find_label(w.conn, "Lan")
    labels.rename_label(w.conn, lid, "Cô Lan", "_Khac")
    reconcile_exports(w.conn, w.config)
    assert (w.output_dir / "Lan" / "ghi_chu.txt").exists()
    assert w.folder_files("Cô Lan") == ["a.png", "b.png"]


def test_reconcile_skips_modified_file(tmp_path):
    w, _ = _exported_world(tmp_path)
    (w.output_dir / "Lan" / "a.png").write_bytes(b"da sua")
    lid = labels.find_label(w.conn, "Lan")
    labels.rename_label(w.conn, lid, "Cô Lan", "_Khac")
    res = reconcile_exports(w.conn, w.config)
    assert res.skipped == 1
    assert (w.output_dir / "Lan" / "a.png").read_bytes() == b"da sua"


# ---------------------------------------------------------------- 1.6


def test_disk_space_check(tmp_path):
    ensure_disk_space(tmp_path / "out", 10, free_fn=lambda p: 10**12)
    with pytest.raises(FacesortError) as e:
        ensure_disk_space(tmp_path / "out", 10**9, free_fn=lambda p: 10**8)
    assert "không đủ chỗ" in str(e.value)


def test_export_full_stops_before_copy_when_disk_full(tmp_path):
    w = fresh(tmp_path)
    make_jpgs(w, ["a.jpg"])
    eng = FakeFaceEngine([faces_for(embs(1))])
    with pytest.raises(FacesortError):
        export_full(w.conn, w.config, tmp_path / "th", lambda: eng, free_fn=lambda p: 0)
    assert not (w.output_dir / "_Khac").exists()


# ---------------------------------------------------------------- ops


def test_ops_label_ignore_detach_undo(tmp_path):
    w = World(tmp_path)
    sha = w.add_photo("a.png", 1)
    c = w.cluster()
    f = w.face(sha, cluster=c)
    lid = ops.label_cluster(w.conn, c, "Ông A", "_Khac")
    assert w.conn.execute("SELECT label_id FROM clusters").fetchone()[0] == lid
    assert ops.undo(w.conn) == "label_cluster"
    assert w.conn.execute("SELECT label_id FROM clusters").fetchone()[0] is None
    assert w.conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 0
    ops.label_cluster(w.conn, c, "Ông A", "_Khac")
    ops.detach_face(w.conn, f)
    r = w.conn.execute("SELECT cluster_id, detached FROM faces").fetchone()
    assert r["cluster_id"] is None and r["detached"] == 1
    assert ops.undo(w.conn) == "detach_face"
    r = w.conn.execute("SELECT cluster_id, detached FROM faces").fetchone()
    assert r["cluster_id"] == c and r["detached"] == 0
    ops.ignore_cluster(w.conn, c)
    r = w.conn.execute("SELECT label_id, ignored FROM clusters").fetchone()
    assert r["label_id"] is None and r["ignored"] == 1
    assert ops.undo(w.conn) == "ignore_cluster"
    assert w.conn.execute("SELECT label_id FROM clusters").fetchone()[0] is not None


def test_ops_same_name_shares_label_and_undo_keeps_label(tmp_path):
    w = World(tmp_path)
    c1, c2 = w.cluster(), w.cluster()
    a = ops.label_cluster(w.conn, c1, "Ông A", "_Khac")
    b = ops.label_cluster(w.conn, c2, "ông a", "_Khac")
    assert a == b
    ops.undo(w.conn)  # nhãn còn được c1 dùng nên không bị xóa
    assert w.conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 1


def test_ops_reserved_and_forbidden_names(tmp_path):
    w = World(tmp_path)
    c = w.cluster()
    with pytest.raises(FacesortError):
        ops.label_cluster(w.conn, c, "_Khac", "_Khac")
    ops.label_cluster(w.conn, c, "Cô Lan / Chú Tư", "_Khac")
    assert w.conn.execute("SELECT folder_name FROM labels").fetchone()[0] == "Cô Lan _ Chú Tư"


def test_ops_label_face_beats_cluster_and_undo_empty(tmp_path):
    w = World(tmp_path)
    sha = w.add_photo("a.png", 1)
    c = w.cluster("Ông A")
    f = w.face(sha, cluster=c)
    ops.label_face(w.conn, f, "Bà B", "_Khac")
    w.export()
    assert w.folder_files("Bà B") == ["a.png"]
    assert ops.undo(w.conn) == "label_face"
    assert ops.undo(w.conn) is None
