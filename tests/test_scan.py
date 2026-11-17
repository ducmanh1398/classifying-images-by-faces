import os

from facesort import db
from facesort.config import Config
from facesort.scan import scan, sha256_file


def make_tree(tmp_path):
    inp = tmp_path / "Ảnh cưới"
    (inp / "sub").mkdir(parents=True)
    (inp / "a.jpg").write_bytes(b"AAA")
    (inp / "sub" / "a_copy.JPG").write_bytes(b"AAA")
    (inp / "b.png").write_bytes(b"BBB")
    (inp / "clip.mp4").write_bytes(b"V")
    (inp / "raw.cr2").write_bytes(b"R")
    (inp / "desktop.ini").write_bytes(b"x")
    (inp / ".hidden.jpg").write_bytes(b"H")
    out = tmp_path / "out"
    (out).mkdir()
    (inp / "sub" / "c.jpg").write_bytes(b"CCC")
    cfg = Config(input_dir=str(inp), output_dir=str(out))
    return inp, cfg


def test_scan_counts_duplicates(tmp_path):
    _, cfg = make_tree(tmp_path)
    conn = db.connect(tmp_path / "t.db")
    s = scan(conn, cfg)
    assert s.files == 4
    assert s.unique_photos == 3
    assert s.duplicate_files == 1
    assert s.skipped_by_ext == {"mp4": 1, "cr2": 1}
    canon = conn.execute(
        "SELECT canonical_path FROM photos WHERE sha256=?",
        (sha256_file(tmp_path / "Ảnh cưới" / "a.jpg"),),
    ).fetchone()[0]
    assert canon == "a.jpg"


def test_second_scan_does_not_hash(tmp_path):
    _, cfg = make_tree(tmp_path)
    conn = db.connect(tmp_path / "t.db")
    scan(conn, cfg)
    calls = []

    def spy(p):
        calls.append(p)
        return sha256_file(p)

    s = scan(conn, cfg, hasher=spy)
    assert calls == [] and s.hashed == 0
    assert s.unique_photos == 3


def test_changed_file_is_rehashed(tmp_path):
    inp, cfg = make_tree(tmp_path)
    conn = db.connect(tmp_path / "t.db")
    scan(conn, cfg)
    p = inp / "b.png"
    p.write_bytes(b"BBBB")
    s = scan(conn, cfg)
    assert s.hashed == 1


def test_deleted_file_not_counted(tmp_path):
    inp, cfg = make_tree(tmp_path)
    conn = db.connect(tmp_path / "t.db")
    scan(conn, cfg)
    os.remove(inp / "b.png")
    s = scan(conn, cfg)
    assert s.files == 3
    assert s.missing == 1
    assert s.unique_photos == 2
    assert db.status_counts(conn)["files"] == 3


def test_deleting_canonical_moves_canonical(tmp_path):
    inp, cfg = make_tree(tmp_path)
    conn = db.connect(tmp_path / "t.db")
    scan(conn, cfg)
    os.remove(inp / "a.jpg")
    scan(conn, cfg)
    row = conn.execute(
        "SELECT canonical_path FROM photos WHERE sha256=?", (sha256_file(inp / "sub/a_copy.JPG"),)
    ).fetchone()
    assert row[0] == "sub/a_copy.JPG"


def test_output_dir_inside_scan_root_is_skipped(tmp_path):
    inp = tmp_path / "in"
    out = tmp_path / "in2"
    inp.mkdir()
    out.mkdir()
    (inp / "a.jpg").write_bytes(b"A")
    (out / "x.jpg").write_bytes(b"X")
    conn = db.connect(tmp_path / "t.db")
    s = scan(conn, Config(input_dir=str(inp), output_dir=str(out)))
    assert s.files == 1
