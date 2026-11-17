import pytest
from typer.testing import CliRunner

from facesort.cli import app
from facesort.config import Config
from facesort.errors import ProjectError
from facesort.project import Project, create_project, resolve_project

runner = CliRunner()


def test_init_vietnamese_path_and_duplicate_rejected(tmp_path):
    inp = tmp_path / "Ảnh cưới"
    inp.mkdir()
    out = tmp_path / "Đầu ra"
    r = runner.invoke(app, ["init", "--input", str(inp), "--output", str(out)])
    assert r.exit_code == 0, r.output
    assert "Ảnh cưới" in r.output
    r2 = runner.invoke(app, ["init", "--input", str(inp), "--output", str(out)])
    assert r2.exit_code != 0


def test_init_rejects_output_inside_input(tmp_path):
    inp = tmp_path / "in"
    inp.mkdir()
    r = runner.invoke(app, ["init", "--input", str(inp), "--output", str(inp / "out")])
    assert r.exit_code != 0


def test_auto_select_single_project(tmp_path):
    cfg = Config(input_dir=str(tmp_path / "a"), output_dir=str(tmp_path / "b"))
    create_project("p1", cfg)
    assert resolve_project(None).name == "p1"
    create_project("p2", cfg)
    with pytest.raises(ProjectError):
        resolve_project(None)
    assert resolve_project("p2").name == "p2"


def test_second_process_lock_fails(tmp_path):
    cfg = Config(input_dir=str(tmp_path / "a"), output_dir=str(tmp_path / "b"))
    project: Project = create_project("p", cfg)
    with project.lock():
        with pytest.raises(ProjectError):
            with project.lock():
                pass
    with project.lock():  # nhả khóa xong thì khóa lại được
        pass


def test_status_runs(tmp_path):
    inp = tmp_path / "in"
    inp.mkdir()
    runner.invoke(app, ["init", "--input", str(inp), "--output", str(tmp_path / "out")])
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 0, r.output
    assert "Ảnh duy nhất" in r.output
