"""Logic xuất thư mục: plan_export() thuần và phần thực thi copy (đặc tả mục 7)."""

from __future__ import annotations

import csv
import os
import shutil
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from . import db
from .config import Config
from .labels import effective_label_id
from .scan import sha256_file

UNLABELED_ID = 0  # label_id dùng trong bảng exports cho thư mục _Khac
LONG_PATH_LIMIT = 240


@dataclass(frozen=True)
class LabelInfo:
    id: int
    name: str
    folder_name: str


@dataclass(frozen=True)
class PhotoInfo:
    sha256: str
    canonical_path: str
    status: str
    has_live_file: bool
    size: int = 0


@dataclass(frozen=True)
class FaceInfo:
    quality_ok: bool
    label: LabelInfo | None  # nhãn hiệu lực đã tính sẵn; None nếu không có


@dataclass(frozen=True)
class Copy:
    src_rel: str
    folder: str
    name: str
    sha256: str
    size: int
    label_id: int


@dataclass
class Plan:
    actions: list[Copy] = field(default_factory=list)
    skipped: list[tuple[str, str, str]] = field(default_factory=list)  # (folder, sha, name)


def pick_dest_name(folder: str, photo: PhotoInfo, taken: set[str]) -> str:
    """Giữ tên gốc; nếu trùng tên (không phân biệt hoa thường) thì thêm 8 ký tự SHA-256."""
    base = PurePosixPath(photo.canonical_path).name
    if base.casefold() not in taken:
        return base
    p = PurePosixPath(base)
    n = 8
    while True:
        cand = f"{p.stem}__{photo.sha256[:n]}{p.suffix}"
        if cand.casefold() not in taken:
            return cand
        n += 1


def plan_export(
    photos: list[PhotoInfo],
    faces: dict[str, list[FaceInfo]],
    existing_hashes: dict[str, set[str]],
    config: Config,
    existing_names: dict[str, set[str]] | None = None,
) -> Plan:
    """Hàm thuần: không đụng vào ổ đĩa. existing_hashes/existing_names bị cập nhật tại chỗ."""
    names = existing_names if existing_names is not None else defaultdict(set)
    plan = Plan()
    for photo in sorted(photos, key=lambda p: p.canonical_path):
        if photo.status != "done" or not photo.has_live_file:
            continue
        labels = {
            f.label.id: f.label for f in faces.get(photo.sha256, []) if f.quality_ok and f.label
        }
        if labels:
            targets = {lab.folder_name: lab.id for lab in labels.values()}
        elif config.export_unlabeled:
            targets = {config.unlabeled_folder: UNLABELED_ID}
        else:
            targets = {}
        for folder in sorted(targets):
            hashes = existing_hashes.setdefault(folder, set())
            taken = names.setdefault(folder, set())
            if photo.sha256 in hashes:
                plan.skipped.append((folder, photo.sha256, photo.canonical_path))
                continue
            name = pick_dest_name(folder, photo, taken)
            plan.actions.append(
                Copy(photo.canonical_path, folder, name, photo.sha256, photo.size, targets[folder])
            )
            hashes.add(photo.sha256)
            taken.add(name.casefold())
    return plan


# ---------------------------------------------------------------- đọc DB


def load_inputs(conn: sqlite3.Connection) -> tuple[list[PhotoInfo], dict[str, list[FaceInfo]]]:
    scan_id = db.current_scan_id(conn)
    photos = [
        PhotoInfo(
            sha256=r["sha256"],
            canonical_path=r["canonical_path"],
            status=r["status"],
            has_live_file=bool(r["live"]),
            size=r["size"] or 0,
        )
        for r in conn.execute(
            "SELECT p.sha256, p.canonical_path, p.status, "
            "EXISTS (SELECT 1 FROM files f WHERE f.sha256=p.sha256 "
            "AND f.last_seen_scan=?) AS live, "
            "(SELECT size FROM files f WHERE f.rel_path=p.canonical_path) AS size FROM photos p",
            (scan_id,),
        )
    ]
    labels = {
        r["id"]: LabelInfo(r["id"], r["name"], r["folder_name"])
        for r in conn.execute("SELECT id, name, folder_name FROM labels")
    }
    faces: dict[str, list[FaceInfo]] = defaultdict(list)
    for r in conn.execute(
        "SELECT f.photo_sha256, f.quality_ok, f.ignored, f.label_id, "
        "c.ignored AS c_ignored, c.label_id AS c_label "
        "FROM faces f LEFT JOIN clusters c ON c.id=f.cluster_id"
    ):
        lid = effective_label_id(
            bool(r["ignored"]), r["label_id"], bool(r["c_ignored"]), r["c_label"]
        )
        faces[r["photo_sha256"]].append(FaceInfo(bool(r["quality_ok"]), labels.get(lid)))
    return photos, faces


# ---------------------------------------------------------------- đĩa


def long_path(p: Path) -> str:
    s = str(p.absolute())
    if sys.platform == "win32" and len(s) > LONG_PATH_LIMIT and not s.startswith("\\\\?\\"):
        s = "\\\\?\\" + s
    return s


def cleanup_part_files(output_dir: Path) -> int:
    n = 0
    if not output_dir.is_dir():
        return 0
    for sub in output_dir.iterdir():
        if sub.is_dir():
            for f in sub.glob("*.part"):
                os.remove(long_path(f))
                n += 1
    return n


def dest_path(output_dir: Path, folder: str, name: str) -> Path:
    return output_dir / folder / name


def build_existing(
    conn: sqlite3.Connection,
    output_dir: Path,
    hasher: Callable[[Path], str] = sha256_file,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Băm file ở đầu ra; dùng lại SHA-256 trong exports nếu đường dẫn, size, mtime khớp."""
    hashes: dict[str, set[str]] = {}
    names: dict[str, set[str]] = {}
    if not output_dir.is_dir():
        return hashes, names
    cache = {
        r["dest_rel_path"]: (r["size"], r["mtime_ns"], r["sha256"])
        for r in conn.execute("SELECT dest_rel_path, size, mtime_ns, sha256 FROM exports")
    }
    for sub in sorted(p for p in output_dir.iterdir() if p.is_dir()):
        hs = hashes.setdefault(sub.name, set())
        ns = names.setdefault(sub.name, set())
        for f in sub.iterdir():
            if not f.is_file() or f.suffix == ".part":
                continue
            st = f.stat()
            ns.add(f.name.casefold())
            cached = cache.get(f"{sub.name}/{f.name}")
            if cached and cached[0] == st.st_size and cached[1] == st.st_mtime_ns:
                hs.add(cached[2])
            else:
                hs.add(hasher(f))
    return hashes, names


@dataclass
class ReportRow:
    folder: str
    dest_name: str
    src_path: str
    sha256: str
    status: str  # copied | skipped_duplicate | error
    message: str = ""


def execute_plan(
    conn: sqlite3.Connection,
    config: Config,
    plan: Plan,
    progress: Callable[[int, int], None] | None = None,
) -> list[ReportRow]:
    input_dir, output_dir = Path(config.input_dir), Path(config.output_dir)
    rows = [ReportRow(f, n, n, s, "skipped_duplicate") for f, s, n in plan.skipped]
    total = len(plan.actions)
    for i, act in enumerate(plan.actions, 1):
        src = input_dir / act.src_rel
        dest = dest_path(output_dir, act.folder, act.name)
        tmp = dest.with_name(dest.name + ".part")
        row = ReportRow(act.folder, act.name, act.src_rel, act.sha256, "copied")
        try:
            if src.stat().st_size != act.size:
                raise OSError("File nguồn đã thay đổi; hãy chạy lại `facesort scan`.")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(long_path(src), long_path(tmp))
            if tmp.stat().st_size != act.size:
                raise OSError("Kích thước file sau khi copy không khớp.")
            os.replace(long_path(tmp), long_path(dest))
            st = dest.stat()
            conn.execute(
                "INSERT OR REPLACE INTO exports "
                "(label_id, sha256, dest_rel_path, size, mtime_ns, exported_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    act.label_id,
                    act.sha256,
                    f"{act.folder}/{act.name}",
                    st.st_size,
                    st.st_mtime_ns,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
        except OSError as e:
            if getattr(e, "errno", None) == 28:  # ENOSPC
                raise
            row.status, row.message = "error", str(e)
            try:
                if tmp.exists():
                    os.remove(long_path(tmp))
            except OSError:
                pass
        rows.append(row)
        if progress:
            progress(i, total)
    return rows


def write_report(output_dir: Path, rows: list[ReportRow]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "export_report.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["thu_muc", "ten_file_dich", "duong_dan_goc", "sha256", "trang_thai", "ghi_chu"])
        for r in rows:
            w.writerow([r.folder, r.dest_name, r.src_path, r.sha256, r.status, r.message])
    return path


# ---------------------------------------------------------------- điều phối


@dataclass
class Preview:
    per_folder: dict[str, int]
    total_files: int
    total_bytes: int
    skipped_existing: int
    duplicate_source_files: int
    error_photos: list[tuple[str, str]]


def make_plan(
    conn: sqlite3.Connection,
    config: Config,
    hasher: Callable[[Path], str] = sha256_file,
) -> Plan:
    photos, faces = load_inputs(conn)
    hashes, names = build_existing(conn, Path(config.output_dir), hasher)
    return plan_export(photos, faces, hashes, config, names)


def build_preview(conn: sqlite3.Connection, plan: Plan) -> Preview:
    per_folder: dict[str, int] = defaultdict(int)
    for a in plan.actions:
        per_folder[a.folder] += 1
    scan_id = db.current_scan_id(conn)
    live_files = conn.execute(
        "SELECT COUNT(*) FROM files WHERE last_seen_scan=?", (scan_id,)
    ).fetchone()[0]
    live_photos = conn.execute(
        "SELECT COUNT(DISTINCT sha256) FROM files WHERE last_seen_scan=?", (scan_id,)
    ).fetchone()[0]
    errors = [
        (r["canonical_path"], r["error"] or "")
        for r in conn.execute("SELECT canonical_path, error FROM photos WHERE status='error'")
    ]
    return Preview(
        per_folder=dict(sorted(per_folder.items())),
        total_files=len(plan.actions),
        total_bytes=sum(a.size for a in plan.actions),
        skipped_existing=len(plan.skipped),
        duplicate_source_files=live_files - live_photos,
        error_photos=errors,
    )


def run_export(
    conn: sqlite3.Connection,
    config: Config,
    dry_run: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[Preview, list[ReportRow]]:
    output_dir = Path(config.output_dir)
    if not dry_run:
        cleanup_part_files(output_dir)
    plan = make_plan(conn, config)
    preview = build_preview(conn, plan)
    if dry_run:
        return preview, []
    rows = execute_plan(conn, config, plan, progress)
    write_report(output_dir, rows)
    return preview, rows
