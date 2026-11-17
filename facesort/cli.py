"""Các lệnh Typer (đặc tả mục 8)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from . import db
from .config import Config
from .errors import FacesortError
from .project import (
    Project,
    create_project,
    resolve_project,
    setup_console,
    setup_logging,
)

app = typer.Typer(help="Phân loại ảnh cưới theo khuôn mặt.", no_args_is_help=True)

ProjectOpt = Annotated[
    str | None, typer.Option("--project", help="Tên dự án (tự chọn nếu chỉ có một).")
]


def _open(project_name: str | None) -> tuple[Project, Config]:
    project = resolve_project(project_name)
    setup_logging(project)
    return project, project.load_config()


@app.command()
def init(
    input: Annotated[Path, typer.Option("--input", help="Folder ảnh gốc.")],
    output: Annotated[Path, typer.Option("--output", help="Folder đầu ra.")],
    name: Annotated[str | None, typer.Option("--name", help="Tên dự án.")] = None,
) -> None:
    """Tạo thư mục dự án, config.toml và cơ sở dữ liệu."""
    cfg = Config(input_dir=str(input.resolve()), output_dir=str(output.resolve()))
    project = create_project(name or input.resolve().name, cfg)
    typer.echo(f"Đã tạo dự án '{project.name}' tại {project.dir}")


@app.command()
def scan(project: ProjectOpt = None) -> None:
    """Bước 1: quét folder gốc, tính SHA-256."""
    from .scan import scan as run_scan

    proj, cfg = _open(project)
    with proj.lock():
        conn = db.connect(proj.db_path)
        try:
            s = run_scan(conn, cfg)
        finally:
            conn.close()
    typer.echo(f"Số file ảnh:        {s.files}")
    typer.echo(f"Ảnh duy nhất:       {s.unique_photos}")
    typer.echo(f"File trùng:         {s.duplicate_files}")
    typer.echo(f"File mới được băm:  {s.hashed}")
    if s.missing:
        typer.echo(f"File đã biến mất:   {s.missing}")
    for ext, n in sorted(s.skipped_by_ext.items()):
        typer.echo(f"Bỏ qua đuôi .{ext}: {n}")
    for err in s.errors:
        typer.echo(f"Lỗi: {err}", err=True)


@app.command()
def status(project: ProjectOpt = None) -> None:
    """In số ảnh, số mặt, số cụm, tiến độ gắn nhãn, số ảnh lỗi."""
    proj, _ = _open(project)
    conn = db.connect(proj.db_path)
    try:
        c = db.status_counts(conn)
        errors = conn.execute("SELECT canonical_path, error FROM photos WHERE status='error'")
        error_rows = list(errors)
    finally:
        conn.close()
    typer.echo(f"Dự án:              {proj.name}")
    typer.echo(f"Số file:            {c['files']}")
    typer.echo(f"Ảnh duy nhất:       {c['photos']} (chờ xử lý {c['photos_pending']})")
    typer.echo(f"Số mặt:             {c['faces']}")
    typer.echo(f"Số cụm:             {c['clusters']} (đã gắn nhãn {c['clusters_labeled']})")
    typer.echo(f"Số nhãn:            {c['labels']}")
    typer.echo(f"Ảnh lỗi:            {c['photos_error']}")
    for row in error_rows:
        typer.echo(f"  {row['canonical_path']}: {row['error']}")


def main() -> None:
    setup_console()
    try:
        app()
    except FacesortError as e:
        typer.echo(f"Lỗi: {e}", err=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
