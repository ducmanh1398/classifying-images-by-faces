import os
import shutil

import pytest

from facesort.export import cleanup_part_files, execute_plan, write_report
from facesort.scan import scan, sha256_file
from tests.factories import World


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def test_T1_same_label_three_faces_one_copy(w):
    sha = w.add_photo("g.png", 1)
    c = w.cluster("Nhà nội")
    for _ in range(3):
        w.face(sha, cluster=c)
    w.export()
    assert w.folder_files("Nhà nội") == ["g.png"]


def test_T2_two_clusters_same_label_one_folder(w):
    s1, s2 = w.add_photo("a.png", 1), w.add_photo("b.png", 2)
    w.face(s1, cluster=w.cluster("Ông A"))
    w.face(s2, cluster=w.cluster("ông a"))
    assert w.conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 1
    w.export()
    assert w.folder_files("Ông A") == ["a.png", "b.png"]
    assert not (w.output_dir / "ông a").exists() or w.folder_files("Ông A")


def test_T3_two_labels_both_folders_byte_identical(w):
    sha = w.add_photo("g.png", 1)
    w.face(sha, cluster=w.cluster("Ông A"))
    w.face(sha, cluster=w.cluster("Bà B"))
    w.export()
    assert w.folder_hashes("Ông A") == [sha]
    assert w.folder_hashes("Bà B") == [sha]


def test_T4_identical_source_files_one_copy_canonical_name(w):
    s = w.add_photo("a.png", 1)
    w.add_photo("sub/a_copy.png", 1)
    w.face(s, cluster=w.cluster("Ông A"))
    w.export()
    assert w.folder_files("Ông A") == ["a.png"]


def test_T5_second_export_copies_nothing(w):
    sha = w.add_photo("a.png", 1)
    w.face(sha, cluster=w.cluster("Ông A"))
    w.add_photo("n.png", 2)
    w.export()
    assert len(w.plan().actions) == 0
    _, rows = w.export()
    assert [r for r in rows if r.status == "copied"] == []


def test_T6_exports_table_lost_still_zero_copies(w):
    sha = w.add_photo("a.png", 1)
    w.face(sha, cluster=w.cluster("Ông A"))
    w.export()
    w.conn.execute("DELETE FROM exports")
    w.conn.commit()
    assert w.plan().actions == []


def test_T6b_exports_cache_reused_without_hashing(w):
    sha = w.add_photo("a.png", 1)
    w.face(sha, cluster=w.cluster("Ông A"))
    w.export()
    from facesort.export import make_plan

    calls = []
    plan = make_plan(w.conn, w.config, hasher=lambda p: calls.append(p) or sha256_file(p))
    assert plan.actions == [] and calls == []


def test_T7_same_name_different_content_gets_suffix(w):
    s1 = w.add_photo("x/IMG_0001.png", 1)
    s2 = w.add_photo("y/IMG_0001.png", 2)
    c = w.cluster("Ông A")
    w.face(s1, cluster=c)
    w.face(s2, cluster=c)
    w.export()
    files = w.folder_files("Ông A")
    assert len(files) == 2
    assert "IMG_0001.png" in files
    other = [f for f in files if f != "IMG_0001.png"][0]
    suffix_sha = s1 if (w.output_dir / "Ông A" / "IMG_0001.png").exists() and sha256_file(
        w.output_dir / "Ông A" / "IMG_0001.png"
    ) == s2 else s2
    assert other == f"IMG_0001__{suffix_sha[:8]}.png"


def test_T7_case_insensitive_name_clash(w):
    s1 = w.add_photo("x/img.png", 1)
    s2 = w.add_photo("y/IMG.png", 2)
    c = w.cluster("Ông A")
    w.face(s1, cluster=c)
    w.face(s2, cluster=c)
    w.export()
    assert len({f.casefold() for f in w.folder_files("Ông A")}) == 2


def test_T8_only_unlabeled_ignored_or_lowquality_go_to_khac(w):
    s1, s2, s3, s4 = (w.add_photo(f"{i}.png", i) for i in range(1, 5))
    w.face(s1, cluster=w.cluster())  # chưa gắn nhãn
    w.face(s2, cluster=w.cluster("Ông A", ignored=True))  # cụm bỏ qua
    w.face(s3, label="Ông A", ignored=True)  # mặt bỏ qua
    w.face(s4, cluster=w.cluster("Ông A"), quality_ok=False)  # chất lượng thấp
    w.add_photo("5.png", 5)  # không mặt nào
    w.export()
    assert w.folder_files("_Khac") == ["1.png", "2.png", "3.png", "4.png", "5.png"]
    assert not (w.output_dir / "Ông A").exists()


def test_R4_unlabeled_can_be_disabled(w):
    w.add_photo("1.png", 1)
    w.config.export_unlabeled = False
    assert w.plan().actions == []


def test_T9_manual_label_beats_cluster(w):
    sha = w.add_photo("a.png", 1)
    c = w.cluster("Ông A")
    w.face(sha, cluster=c, label="Bà B")
    w.export()
    assert w.folder_files("Bà B") == ["a.png"]
    assert not (w.output_dir / "Ông A").exists()


def test_missing_source_not_exported(w):
    sha = w.add_photo("a.png", 1)
    w.face(sha, cluster=w.cluster("Ông A"))
    w.conn.execute("UPDATE files SET last_seen_scan=0")
    w.conn.commit()
    assert w.plan().actions == []


def test_pending_or_error_photo_not_exported(w):
    w.add_photo("a.png", 1, status="pending")
    w.add_photo("b.png", 2, status="error")
    assert w.plan().actions == []


def test_T10_source_untouched_with_scan_and_export(tmp_path):
    w = World(tmp_path)
    w.conn.execute("DELETE FROM meta")
    w.conn.commit()
    sha = w.add_photo("a.png", 1)
    w.add_photo("sub/b.png", 2)
    w.face(sha, cluster=w.cluster("Ông A"))

    def snap():
        return {
            str(p.relative_to(w.input_dir)): (sha256_file(p), p.stat().st_mtime_ns)
            for p in w.input_dir.rglob("*")
            if p.is_file()
        }

    before = snap()
    scan(w.conn, w.config)
    w.export()
    assert snap() == before


def test_dry_run_creates_nothing_and_matches_real(w):
    s1, s2 = w.add_photo("a.png", 1), w.add_photo("b.png", 2)
    w.add_photo("c.png", 2)
    w.face(s1, cluster=w.cluster("Ông A"))
    w.face(s1, cluster=w.cluster("Bà B"))
    w.face(s2, cluster=w.cluster("Ông A"))
    preview, rows = w.export(dry_run=True)
    assert not w.output_dir.exists() and rows == []
    assert preview.per_folder == {"Bà B": 1, "Ông A": 2}
    assert preview.total_files == 3
    assert preview.duplicate_source_files == 1
    real, rows = w.export()
    assert real.total_files == len([r for r in rows if r.status == "copied"])
    assert preview.total_bytes == sum(
        p.stat().st_size for p in w.output_dir.rglob("*.png")
    )


def test_report_csv_written(w):
    w.face(w.add_photo("a.png", 1), cluster=w.cluster("Ông A"))
    w.export()
    text = (w.output_dir / "export_report.csv").read_text(encoding="utf-8-sig")
    assert "copied" in text and "Ông A" in text


def test_interrupted_copy_leaves_no_real_file_and_part_cleaned(w, monkeypatch):
    w.face(w.add_photo("a.png", 1), cluster=w.cluster("Ông A"))
    real_copy = shutil.copy2

    def boom(src, dst, *a, **k):
        with open(dst, "wb") as f:
            f.write(b"par")
        raise KeyboardInterrupt

    monkeypatch.setattr(shutil, "copy2", boom)
    with pytest.raises(KeyboardInterrupt):
        w.export()
    assert not (w.output_dir / "Ông A" / "a.png").exists()
    assert (w.output_dir / "Ông A" / "a.png.part").exists()
    monkeypatch.setattr(shutil, "copy2", real_copy)
    w.export()
    assert w.folder_files("Ông A") == ["a.png"]


def test_cleanup_part_files(w):
    d = w.output_dir / "X"
    d.mkdir(parents=True)
    (d / "z.jpg.part").write_bytes(b"1")
    assert cleanup_part_files(w.output_dir) == 1


def test_source_changed_reports_error_and_continues(w):
    s1, s2 = w.add_photo("a.png", 1), w.add_photo("b.png", 2)
    c = w.cluster("Ông A")
    w.face(s1, cluster=c)
    w.face(s2, cluster=c)
    (w.input_dir / "a.png").write_bytes(b"changed")
    _, rows = w.export()
    st = {r.dest_name: r.status for r in rows}
    assert st == {"a.png": "error", "b.png": "copied"}


def test_T12_forbidden_chars_label_folder(w):
    sha = w.add_photo("a.png", 1)
    w.face(sha, cluster=w.cluster("Cô Lan / Chú Tư"))
    w.export()
    assert w.folder_files("Cô Lan _ Chú Tư") == ["a.png"]


def test_long_path_prefix(tmp_path):
    from facesort.export import long_path

    p = tmp_path / ("d" * 120) / ("e" * 120) / "f.png"
    s = long_path(p)
    if os.name == "nt":
        assert s.startswith("\\\\?\\")
    assert execute_plan and write_report  # import guard
