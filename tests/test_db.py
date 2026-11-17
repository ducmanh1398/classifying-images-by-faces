import sqlite3

from facesort import db


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_new_db_has_schema(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    assert {"files", "photos", "faces", "clusters", "labels", "exports"} <= tables(conn)
    assert db.current_version(conn) == db.LATEST
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_reopen_existing(tmp_path):
    p = tmp_path / "x.db"
    db.connect(p).close()
    conn = db.connect(p)
    assert db.current_version(conn) == db.LATEST
    assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == len(db.MIGRATIONS)


def test_migration_from_zero_to_one(tmp_path):
    conn = sqlite3.connect(tmp_path / "y.db")
    assert db.current_version(conn) == 0
    db.migrate(conn, 1)
    assert db.current_version(conn) == 1
    assert "files" in tables(conn)


def test_meta(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    assert db.get_meta(conn, "k") is None
    db.set_meta(conn, "k", "1")
    db.set_meta(conn, "k", "2")
    assert db.get_meta(conn, "k") == "2"


def test_migration_v1_to_v2_keeps_data(tmp_path):
    conn = sqlite3.connect(tmp_path / "z.db")
    conn.row_factory = sqlite3.Row
    db.migrate(conn, 1)
    conn.execute("INSERT INTO photos (sha256, canonical_path) VALUES ('a', 'a.jpg')")
    conn.execute(
        "INSERT INTO faces (photo_sha256,x,y,w,h,det_score) VALUES ('a',0,0,1,1,.9)"
    )
    conn.commit()
    db.migrate(conn)
    assert db.current_version(conn) == 2
    assert conn.execute("SELECT detached FROM faces").fetchone()[0] == 0
    assert "ops_log" in tables(conn)
