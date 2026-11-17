"""Thư mục dự án, khóa tiến trình, log, console UTF-8 (đặc tả mục 4, 9)."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import Config, load_config, save_config
from .errors import ProjectError

_BAD_NAME_CHARS = '<>:"/\\|?*'


def setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def data_root() -> Path:
    override = os.environ.get("FACESORT_HOME")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "facesort" if base else Path.home() / ".facesort"


def validate_project_name(name: str) -> str:
    name = name.strip()
    if not name or any(c in name for c in _BAD_NAME_CHARS) or name in {".", ".."}:
        raise ProjectError(f"Tên dự án không hợp lệ: {name!r}")
    return name


@dataclass
class Project:
    name: str
    dir: Path

    @property
    def config_path(self) -> Path:
        return self.dir / "config.toml"

    @property
    def db_path(self) -> Path:
        return self.dir / "facesort.db"

    @property
    def logs_dir(self) -> Path:
        return self.dir / "logs"

    def load_config(self) -> Config:
        return load_config(self.config_path)

    def lock(self) -> ProjectLock:
        return ProjectLock(self.dir / "facesort.lock")


def list_projects() -> list[str]:
    root = data_root()
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "config.toml").exists())


def create_project(name: str, config: Config) -> Project:
    from . import db

    name = validate_project_name(name)
    config.validate()
    pdir = data_root() / name
    if pdir.exists() and (pdir / "config.toml").exists():
        raise ProjectError(f"Dự án '{name}' đã tồn tại.")
    for sub in ("logs", "thumbs/faces", "thumbs/photos"):
        (pdir / sub).mkdir(parents=True, exist_ok=True)
    save_config(config, pdir / "config.toml")
    db.connect(pdir / "facesort.db").close()
    return Project(name, pdir)


def resolve_project(name: str | None) -> Project:
    projects = list_projects()
    if name is None:
        if not projects:
            raise ProjectError("Chưa có dự án nào. Chạy `facesort init` trước.")
        if len(projects) > 1:
            raise ProjectError(
                "Có nhiều dự án, hãy chỉ định bằng --project. Hiện có: " + ", ".join(projects)
            )
        name = projects[0]
    elif name not in projects:
        raise ProjectError(f"Không tìm thấy dự án '{name}'.")
    return Project(name, data_root() / name)


def setup_logging(project: Project) -> None:
    project.logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("facesort")
    if any(isinstance(h, logging.FileHandler) for h in root.handlers):
        return
    handler = logging.FileHandler(project.logs_dir / "facesort.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


class ProjectLock:
    """Khóa file không chặn; hệ điều hành tự nhả khi tiến trình chết."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def __enter__(self) -> ProjectLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")  # noqa: SIM115
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            raise ProjectError(
                "Dự án đang được một tiến trình facesort khác sử dụng. "
                "Hãy đóng cửa sổ facesort đang chạy rồi thử lại."
            ) from None
        self._fh = fh
        return self

    def __exit__(self, *exc) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()
