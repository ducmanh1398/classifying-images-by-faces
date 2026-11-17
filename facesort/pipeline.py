"""Luồng dùng chung cho CLI và giao diện: Scan và Export đầy đủ (UI_PLAN mục 3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import db
from .cluster import ClusterSummary, cluster_run
from .config import Config
from .detect import DetectSummary, FaceEngine, run_detect
from .export import (
    Preview,
    ReconcileResult,
    ReportRow,
    build_preview,
    cleanup_part_files,
    ensure_disk_space,
    execute_plan,
    make_plan,
    reconcile_exports,
    write_report,
)
from .scan import ScanSummary, scan

# progress(bước, đã xong, tổng); tổng = 0 nghĩa là chưa biết
Progress = Callable[[str, int, int], None]
EngineFactory = Callable[[], FaceEngine]


@dataclass
class ScanAllResult:
    scan: ScanSummary
    detect: DetectSummary = field(default_factory=DetectSummary)
    cluster: ClusterSummary | None = None
    cancelled: bool = False


@dataclass
class ExportResult:
    scan_all: ScanAllResult
    preview: Preview | None = None
    rows: list[ReportRow] = field(default_factory=list)
    reconciled: ReconcileResult | None = None
    unlabeled_clusters: int = 0
    cancelled: bool = False


def _count_pending(conn: sqlite3.Connection) -> int:
    scan_id = db.current_scan_id(conn)
    return conn.execute(
        "SELECT COUNT(DISTINCT p.sha256) FROM photos p JOIN files f ON f.sha256=p.sha256 "
        "AND f.last_seen_scan=? WHERE p.status IN ('pending','error')",
        (scan_id,),
    ).fetchone()[0]


def scan_all(
    conn: sqlite3.Connection,
    config: Config,
    thumbs_dir: Path,
    engine_factory: EngineFactory,
    progress: Progress | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> ScanAllResult:
    """Quét → phát hiện mặt ảnh mới → gom cụm / gán tăng dần."""
    p = progress or (lambda *_: None)
    p("scan", 0, 0)
    result = ScanAllResult(scan(conn, config, progress=lambda n: p("scan", n, 0)))
    if should_stop and should_stop():
        result.cancelled = True
        return result
    if _count_pending(conn):
        p("model", 0, 0)
        engine = engine_factory()
        result.detect = run_detect(
            conn,
            config,
            engine,
            thumbs_dir,
            progress=lambda i, n: p("detect", i, n),
            should_stop=should_stop,
        )
        if result.detect.cancelled:
            result.cancelled = True
            return result
    p("cluster", 0, 0)
    result.cluster = cluster_run(conn, config)
    return result


def export_full(
    conn: sqlite3.Connection,
    config: Config,
    thumbs_dir: Path,
    engine_factory: EngineFactory,
    progress: Progress | None = None,
    should_stop: Callable[[], bool] | None = None,
    free_fn: Callable[[Path], int] | None = None,
) -> ExportResult:
    """Quét lại input, xử lý ảnh mới, gán tăng dần, kiểm tra ổ đĩa, copy, ghi báo cáo."""
    p = progress or (lambda *_: None)
    sa = scan_all(conn, config, thumbs_dir, engine_factory, progress, should_stop)
    result = ExportResult(sa)
    if sa.cancelled:
        result.cancelled = True
        return result
    output_dir = Path(config.output_dir)
    p("plan", 0, 0)
    cleanup_part_files(output_dir)
    result.reconciled = reconcile_exports(conn, config)
    plan = make_plan(conn, config)
    result.preview = build_preview(conn, plan)
    ensure_disk_space(output_dir, result.preview.total_bytes, free_fn)
    result.rows = execute_plan(
        conn, config, plan, progress=lambda i, n: p("export", i, n), should_stop=should_stop
    )
    copied_or_failed = sum(r.status != "skipped_duplicate" for r in result.rows)
    result.cancelled = copied_or_failed < len(plan.actions)
    write_report(output_dir, result.rows)
    result.unlabeled_clusters = conn.execute(
        "SELECT COUNT(*) FROM clusters WHERE label_id IS NULL AND ignored=0"
    ).fetchone()[0]
    return result
