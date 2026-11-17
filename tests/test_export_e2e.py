"""Tích hợp giai đoạn 2: init -> scan -> nhãn giả -> export qua CLI, đường dẫn tiếng Việt."""

from typer.testing import CliRunner

from facesort import db, labels
from facesort.cli import app
from facesort.project import resolve_project
from tests.factories import tiny_png

runner = CliRunner()


def test_cli_scan_export_roundtrip(tmp_path):
    inp = tmp_path / "Ảnh cưới"
    (inp / "Họ hàng").mkdir(parents=True)
    (inp / "Họ hàng" / "ảnh 1.png").write_bytes(tiny_png(1))
    (inp / "ảnh 2.png").write_bytes(tiny_png(2))
    out = tmp_path / "Kết quả"
    assert runner.invoke(app, ["init", "--input", str(inp), "--output", str(out)]).exit_code == 0
    assert runner.invoke(app, ["scan"]).exit_code == 0

    proj = resolve_project(None)
    conn = db.connect(proj.db_path)
    conn.execute("UPDATE photos SET status='done'")
    lid = labels.get_or_create_label(conn, "Cô Lan / Chú Tư", "_Khac")
    cid = conn.execute("INSERT INTO clusters (label_id) VALUES (?)", (lid,)).lastrowid
    sha = conn.execute("SELECT sha256 FROM photos WHERE canonical_path='Họ hàng/ảnh 1.png'")
    sha = sha.fetchone()[0]
    conn.execute(
        "INSERT INTO faces (photo_sha256,x,y,w,h,det_score,quality_ok,cluster_id) "
        "VALUES (?,0,0,1,1,.9,1,?)",
        (sha, cid),
    )
    conn.commit()
    conn.close()

    r = runner.invoke(app, ["export", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert not out.exists()
    r = runner.invoke(app, ["export"])
    assert r.exit_code == 0, r.output
    assert (out / "Cô Lan _ Chú Tư" / "ảnh 1.png").exists()
    assert (out / "_Khac" / "ảnh 2.png").exists()
    assert (out / "export_report.csv").exists()
    r = runner.invoke(app, ["export"])
    assert "Đã copy: 0" in r.output
