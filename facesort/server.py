"""Máy chủ web cục bộ (FastAPI), chỉ nghe trên 127.0.0.1 (UI_PLAN mục 2, 6)."""

from __future__ import annotations

import dataclasses
import io
import logging
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import ImageDraw

from . import db, imaging, ops
from . import labels as lb
from .cluster import cluster_centroids, representatives, suggest_merges
from .config import Config, save_config
from .detect import FaceEngine
from .errors import ConfigError, FacesortError, ProjectError
from .jobs import JobBusy, JobRunner
from .pipeline import export_full, scan_all
from .project import (
    Project,
    create_project,
    list_projects,
    resolve_project,
    setup_logging,
    validate_project_name,
)

log = logging.getLogger("facesort.server")

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
PAGE_SIZE = 24
LOOSE_PAGE_SIZE = 48

EngineFactory = Callable[[Config], FaceEngine]


def default_engine_factory(config: Config) -> FaceEngine:
    from .detect import InsightFaceEngine

    return InsightFaceEngine(config.det_size)


def pick_folder(initial: str | None = None) -> str | None:
    """Mở hộp thoại chọn folder bằng tkinter trong tiến trình con (tránh treo máy chủ)."""
    code = (
        "import sys, tkinter as tk\nfrom tkinter import filedialog\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "p = filedialog.askdirectory(initialdir=sys.argv[1] or None, mustexist=True)\n"
        "sys.stdout.buffer.write(p.encode('utf-8'))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, initial or ""], capture_output=True, timeout=600, check=True
    )
    return out.stdout.decode("utf-8").strip() or None


def open_folder(path: Path) -> None:
    os.startfile(str(path))  # type: ignore[attr-defined]  # chỉ có trên Windows


class AppState:
    def __init__(self, project: Project | None, engine_factory: EngineFactory):
        self.project = project
        self.engine_factory = engine_factory
        self.runner = JobRunner()
        self._centroids: dict | None = None

    def invalidate(self) -> None:
        self._centroids = None

    def centroids(self, conn) -> dict:
        if self._centroids is None:
            self._centroids = cluster_centroids(conn)
        return self._centroids


def _err(status: int, msg: str) -> HTTPException:
    return HTTPException(status, msg)


def create_app(
    project_name: str | None = None,
    engine_factory: EngineFactory = default_engine_factory,
) -> FastAPI:
    project = None
    if project_name is not None:
        project = resolve_project(project_name)
    else:
        names = list_projects()
        if len(names) == 1:
            project = resolve_project(names[0])
    state = AppState(project, engine_factory)
    if project:
        setup_logging(project)

    app = FastAPI(title="facesort", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.fs = state

    # ------------------------------------------------------------ bảo mật
    @app.middleware("http")
    async def host_guard(request: Request, call_next):
        host = (request.headers.get("host") or "").split(":")[0].strip("[]")
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"error": "Truy cập bị từ chối."}, status_code=403)
        origin = request.headers.get("origin")
        if origin and (urlparse(origin).hostname or "") not in ALLOWED_HOSTS:
            return JSONResponse({"error": "Truy cập bị từ chối."}, status_code=403)
        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def http_exc(_: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exc(_: Request, __: RequestValidationError):
        return JSONResponse({"error": "Dữ liệu gửi lên không hợp lệ."}, status_code=422)

    @app.exception_handler(FacesortError)
    async def fs_exc(_: Request, exc: FacesortError):
        return JSONResponse({"error": str(exc)}, status_code=422)

    # ------------------------------------------------------------ tiện ích
    def need_project() -> Project:
        if state.project is None:
            raise _err(409, "Chưa có dự án. Hãy chọn folder ảnh và tạo dự án trước.")
        return state.project

    @contextmanager
    def conn_for(write: bool = False) -> Iterator:
        proj = need_project()
        if write and state.runner.is_running():
            raise _err(409, "Đang chạy tác vụ nền; hãy chờ xong rồi thử lại.")
        conn = db.connect(proj.db_path)
        try:
            yield conn
        finally:
            conn.close()
            if write:
                state.invalidate()

    def config() -> Config:
        return need_project().load_config()

    def check_folders(cfg: Config) -> None:
        if not Path(cfg.input_dir).is_dir():
            raise ConfigError("Không tìm thấy folder input. Kiểm tra lại đường dẫn.")
        cfg.validate()

    # ------------------------------------------------------------ dự án và cấu hình
    @app.get("/api/projects")
    def projects():
        return {"projects": list_projects(), "current": state.project.name if state.project else None}

    @app.post("/api/projects")
    def new_project(payload: dict[str, Any] = Body(...)):
        if state.runner.is_running():
            raise _err(409, "Đang chạy tác vụ nền; hãy chờ xong rồi thử lại.")
        inp = Path(str(payload.get("input_dir", "")).strip())
        out = str(payload.get("output_dir", "")).strip()
        if not str(inp) or str(inp) == "." or not out:
            raise ConfigError("Hãy nhập cả folder input và folder output.")
        name = (payload.get("name") or inp.resolve().name or "").strip()
        cfg = Config(input_dir=str(inp.resolve()), output_dir=str(Path(out).resolve()))
        check_folders(cfg)
        validate_project_name(name)
        state.project = create_project(name, cfg)
        setup_logging(state.project)
        state.invalidate()
        return {"name": state.project.name}

    @app.post("/api/projects/select")
    def select_project(payload: dict[str, Any] = Body(...)):
        if state.runner.is_running():
            raise _err(409, "Đang chạy tác vụ nền; hãy chờ xong rồi thử lại.")
        state.project = resolve_project(str(payload.get("name", "")))
        setup_logging(state.project)
        state.invalidate()
        return {"name": state.project.name}

    @app.get("/api/config")
    def get_config():
        cfg = config()
        d = dataclasses.asdict(cfg)
        d["extensions"] = list(cfg.extensions)
        return {"project": need_project().name, "config": d}

    @app.put("/api/config")
    def put_config(payload: dict[str, Any] = Body(...)):
        proj = need_project()
        if state.runner.is_running():
            raise _err(409, "Đang chạy tác vụ nền; hãy chờ xong rồi thử lại.")
        cur = proj.load_config()
        fields = {f.name: f for f in dataclasses.fields(Config)}
        changes: dict[str, Any] = {}
        for k, v in (payload.get("config", payload)).items():
            if k not in fields:
                raise ConfigError(f"Không có thiết lập '{k}'.")
            ftype = type(getattr(cur, k))
            try:
                if ftype is tuple:
                    v = tuple(str(x) for x in v)
                elif ftype is bool:
                    if not isinstance(v, bool):
                        raise ValueError
                else:
                    v = ftype(v)
            except (TypeError, ValueError):
                raise ConfigError(f"Giá trị của '{k}' không hợp lệ.") from None
            changes[k] = v
        new = dataclasses.replace(cur, **changes)
        check_folders(new)
        save_config(new, proj.config_path)
        return {"ok": True}

    @app.post("/api/pick-folder")
    def pick(payload: dict[str, Any] = Body(default={})):
        try:
            path = pick_folder(payload.get("initial"))
        except Exception:  # noqa: BLE001 - tkinter có thể không có
            raise _err(501, "Máy này không mở được hộp thoại chọn folder. Hãy dán đường dẫn.") from None
        return {"path": path}

    # ------------------------------------------------------------ trạng thái và tác vụ
    @app.get("/api/status")
    def status():
        with conn_for() as conn:
            c = db.status_counts(conn)
            q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
            return {
                "project": state.project.name,
                "files": c["files"],
                "photos": c["photos"],
                "photos_pending": c["photos_pending"],
                "photos_error": c["photos_error"],
                "faces": c["faces"],
                "clusters": q("SELECT COUNT(*) FROM clusters WHERE ignored=0"),
                "clusters_labeled": q(
                    "SELECT COUNT(*) FROM clusters WHERE ignored=0 AND label_id IS NOT NULL"
                ),
                "clusters_ignored": q("SELECT COUNT(*) FROM clusters WHERE ignored=1"),
                "labels": c["labels"],
                "loose_faces": q(
                    "SELECT COUNT(*) FROM faces WHERE cluster_id IS NULL AND quality_ok=1 "
                    "AND ignored=0 AND label_id IS NULL"
                ),
                "job": state.runner.snapshot(),
            }

    def start_job(kind: str, work: Callable[..., dict]) -> dict:
        proj = need_project()
        cfg = config()
        check_folders(cfg)
        thumbs = proj.dir / "thumbs" / "faces"

        def fn(progress, should_stop):
            conn = db.connect(proj.db_path)
            try:
                return work(conn, cfg, thumbs, progress, should_stop)
            finally:
                conn.close()
                state.invalidate()

        try:
            state.runner.start(kind, fn, proj.lock())
        except JobBusy as e:
            raise _err(409, str(e)) from None
        return state.runner.snapshot()

    def engine_for(cfg: Config) -> Callable[[], FaceEngine]:
        return lambda: state.engine_factory(cfg)

    @app.post("/api/jobs/scan")
    def job_scan():
        def work(conn, cfg, thumbs, progress, should_stop):
            r = scan_all(conn, cfg, thumbs, engine_for(cfg), progress, should_stop)
            cl = r.cluster
            return {
                "cancelled": r.cancelled,
                "files": r.scan.files,
                "photos": r.scan.unique_photos,
                "duplicate_files": r.scan.duplicate_files,
                "faces_found": r.detect.faces,
                "photo_errors": r.detect.errors,
                "clusters": cl.clusters if cl else None,
                "assigned": cl.assigned if cl else 0,
                "new_clusters": cl.new_clusters if cl else 0,
            }

        return start_job("scan", work)

    @app.post("/api/jobs/export")
    def job_export():
        def work(conn, cfg, thumbs, progress, should_stop):
            r = export_full(conn, cfg, thumbs, engine_for(cfg), progress, should_stop)
            cl = r.scan_all.cluster
            out: dict[str, Any] = {
                "cancelled": r.cancelled,
                "assigned": cl.assigned if cl else 0,
                "unlabeled_clusters": r.unlabeled_clusters,
                "output_dir": cfg.output_dir,
            }
            if r.preview:
                p = r.preview
                errors = [
                    {"folder": x.folder, "name": x.dest_name, "message": x.message}
                    for x in r.rows
                    if x.status == "error"
                ]
                out.update(
                    per_folder=p.per_folder,
                    total_files=p.total_files,
                    total_bytes=p.total_bytes,
                    skipped_existing=p.skipped_existing,
                    duplicate_source_files=p.duplicate_source_files,
                    error_photos=[{"path": a, "message": b} for a, b in p.error_photos],
                    copied=sum(x.status == "copied" for x in r.rows),
                    errors=errors,
                    reconciled=dataclasses.asdict(r.reconciled) if r.reconciled else None,
                )
            return out

        return start_job("export", work)

    @app.get("/api/job")
    def job():
        return state.runner.snapshot()

    @app.post("/api/job/cancel")
    def job_cancel():
        state.runner.cancel()
        return state.runner.snapshot()

    @app.post("/api/open-output")
    def open_output():
        out = Path(config().output_dir)
        if not out.is_dir():
            raise _err(404, "Folder output chưa có. Hãy chạy Export trước.")
        try:
            open_folder(out)
        except Exception:  # noqa: BLE001
            raise _err(501, "Máy này không mở được folder tự động.") from None
        return {"ok": True}

    # ------------------------------------------------------------ nhóm
    def cluster_card(conn, row, centroids) -> dict:
        main, small = representatives(conn, row["id"], k=5)
        hint = None
        if row["label_id"] is None and not row["ignored"]:
            for s in suggest_merges(conn, row["id"], centroids=centroids, limit=5):
                if s["label"]:
                    hint = {"label": s["label"], "distance": round(s["distance"], 3)}
                    break
        return {
            "id": row["id"],
            "faces": row["n_faces"],
            "photos": row["n_photos"],
            "label": row["label"],
            "label_id": row["label_id"],
            "ignored": bool(row["ignored"]),
            "main_face": main,
            "small_faces": small,
            "hint": hint,
        }

    @app.get("/api/clusters")
    def clusters(filter: str = "unlabeled", page: int = 1, page_size: int = PAGE_SIZE):
        page_size = max(1, min(page_size, 100))
        where = {
            "all": "1=1",
            "unlabeled": "c.label_id IS NULL AND c.ignored=0",
            "labeled": "c.label_id IS NOT NULL AND c.ignored=0",
            "ignored": "c.ignored=1",
        }.get(filter)
        if where is None:
            raise _err(422, "Bộ lọc không hợp lệ.")
        with conn_for() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM clusters c WHERE {where}").fetchone()[0]
            rows = conn.execute(
                "SELECT c.id, c.label_id, c.ignored, l.name AS label, "
                "COUNT(f.id) AS n_faces, COUNT(DISTINCT f.photo_sha256) AS n_photos "
                "FROM clusters c LEFT JOIN faces f ON f.cluster_id=c.id "
                "LEFT JOIN labels l ON l.id=c.label_id "
                f"WHERE {where} GROUP BY c.id ORDER BY n_faces DESC, c.id LIMIT ? OFFSET ?",
                (page_size, (max(page, 1) - 1) * page_size),
            ).fetchall()
            cents = state.centroids(conn)
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [cluster_card(conn, r, cents) for r in rows],
            }

    @app.get("/api/clusters/{cluster_id}/faces")
    def cluster_faces(cluster_id: int):
        with conn_for() as conn:
            if not conn.execute("SELECT 1 FROM clusters WHERE id=?", (cluster_id,)).fetchone():
                raise _err(404, "Không tìm thấy nhóm.")
            rows = conn.execute(
                "SELECT id, photo_sha256, det_score, w, h FROM faces WHERE cluster_id=? "
                "ORDER BY det_score DESC",
                (cluster_id,),
            ).fetchall()
            return {
                "faces": [
                    {"id": r["id"], "photo": r["photo_sha256"], "score": round(r["det_score"], 3),
                     "size": int(min(r["w"], r["h"]))}
                    for r in rows
                ]
            }

    @app.get("/api/clusters/{cluster_id}/suggest-merge")
    def suggest(cluster_id: int):
        with conn_for() as conn:
            if not conn.execute("SELECT 1 FROM clusters WHERE id=?", (cluster_id,)).fetchone():
                raise _err(404, "Không tìm thấy nhóm.")
            out = []
            for s in suggest_merges(conn, cluster_id, centroids=state.centroids(conn)):
                main, _ = representatives(conn, s["cluster_id"], k=0)
                out.append({**s, "distance": round(s["distance"], 3), "main_face": main})
            return {"suggestions": out}

    @app.put("/api/clusters/{cluster_id}/label")
    def label_cluster(cluster_id: int, payload: dict[str, Any] = Body(...)):
        cfg = config()
        with conn_for(write=True) as conn:
            lid = ops.label_cluster(conn, cluster_id, str(payload.get("name", "")), cfg.unlabeled_folder)
            name = conn.execute("SELECT name FROM labels WHERE id=?", (lid,)).fetchone()[0]
        return {"label_id": lid, "label": name}

    @app.post("/api/clusters/{cluster_id}/ignore")
    def ignore_cluster(cluster_id: int, payload: dict[str, Any] = Body(default={})):
        with conn_for(write=True) as conn:
            ops.ignore_cluster(conn, cluster_id, bool(payload.get("ignored", True)))
        return {"ok": True}

    # ------------------------------------------------------------ khuôn mặt
    def _face_must_exist(conn, face_id: int) -> None:
        if not conn.execute("SELECT 1 FROM faces WHERE id=?", (face_id,)).fetchone():
            raise _err(404, "Không tìm thấy khuôn mặt.")

    @app.post("/api/faces/{face_id}/detach")
    def detach(face_id: int):
        with conn_for(write=True) as conn:
            _face_must_exist(conn, face_id)
            ops.detach_face(conn, face_id)
        return {"ok": True}

    @app.put("/api/faces/{face_id}/label")
    def label_face(face_id: int, payload: dict[str, Any] = Body(...)):
        cfg = config()
        with conn_for(write=True) as conn:
            _face_must_exist(conn, face_id)
            lid = ops.label_face(conn, face_id, str(payload.get("name", "")), cfg.unlabeled_folder)
        return {"label_id": lid}

    @app.post("/api/faces/{face_id}/ignore")
    def ignore_face(face_id: int, payload: dict[str, Any] = Body(default={})):
        with conn_for(write=True) as conn:
            _face_must_exist(conn, face_id)
            ops.ignore_face(conn, face_id, bool(payload.get("ignored", True)))
        return {"ok": True}

    @app.get("/api/faces/loose")
    def loose_faces(page: int = 1):
        with conn_for() as conn:
            where = (
                "cluster_id IS NULL AND quality_ok=1 AND ignored=0 AND label_id IS NULL"
            )
            total = conn.execute(f"SELECT COUNT(*) FROM faces WHERE {where}").fetchone()[0]
            rows = conn.execute(
                f"SELECT id, photo_sha256, embedding FROM faces WHERE {where} "
                "ORDER BY det_score * MIN(w, h) DESC LIMIT ? OFFSET ?",
                (LOOSE_PAGE_SIZE, (max(page, 1) - 1) * LOOSE_PAGE_SIZE),
            ).fetchall()
            labeled = {
                cid: (c, n)
                for cid, (c, n) in state.centroids(conn).items()
                if conn.execute(
                    "SELECT 1 FROM clusters WHERE id=? AND label_id IS NOT NULL", (cid,)
                ).fetchone()
            }
            names = {
                r["id"]: r["name"]
                for r in conn.execute(
                    "SELECT c.id, l.name FROM clusters c JOIN labels l ON l.id=c.label_id"
                )
            }
            items = []
            for r in rows:
                hint = None
                if labeled and r["embedding"]:
                    v = np.frombuffer(r["embedding"], dtype=np.float32)
                    best = min(labeled, key=lambda cid: 1.0 - float(v @ labeled[cid][0]))
                    d = 1.0 - float(v @ labeled[best][0])
                    if d <= 0.6:
                        hint = {"label": names[best], "distance": round(d, 3)}
                items.append({"id": r["id"], "photo": r["photo_sha256"], "hint": hint})
            return {"total": total, "page": page, "page_size": LOOSE_PAGE_SIZE, "items": items}

    # ------------------------------------------------------------ nhãn, hoàn tác
    @app.get("/api/labels")
    def labels_list():
        with conn_for() as conn:
            rows = conn.execute(
                "SELECT l.id, l.name, l.folder_name, "
                "(SELECT COUNT(DISTINCT f.photo_sha256) FROM faces f "
                " LEFT JOIN clusters c ON c.id=f.cluster_id "
                " WHERE f.ignored=0 AND f.quality_ok=1 AND COALESCE(c.ignored,0)=0 "
                " AND COALESCE(f.label_id, c.label_id)=l.id) AS photos "
                "FROM labels l ORDER BY l.name COLLATE NOCASE"
            ).fetchall()
            return {"labels": [dict(r) for r in rows]}

    @app.patch("/api/labels/{label_id}")
    def rename_label(label_id: int, payload: dict[str, Any] = Body(...)):
        cfg = config()
        with conn_for(write=True) as conn:
            if not conn.execute("SELECT 1 FROM labels WHERE id=?", (label_id,)).fetchone():
                raise _err(404, "Không tìm thấy nhãn.")
            kept = lb.rename_label(conn, label_id, str(payload.get("name", "")), cfg.unlabeled_folder)
        return {"label_id": kept, "merged": kept != label_id}

    @app.post("/api/undo")
    def undo():
        with conn_for(write=True) as conn:
            kind = ops.undo(conn)
        if kind is None:
            raise _err(404, "Không có thao tác nào để hoàn tác.")
        return {"undone": kind}

    # ------------------------------------------------------------ ảnh
    @app.get("/thumbs/faces/{face_id}.jpg")
    def face_thumb(face_id: int):
        path = need_project().dir / "thumbs" / "faces" / f"{face_id}.jpg"
        if not path.is_file():
            raise _err(404, "Không có ảnh khuôn mặt.")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    @app.get("/api/photos/{sha}/preview")
    def photo_preview(sha: str, face: int | None = None):
        if not SHA_RE.match(sha):
            raise _err(404, "Không tìm thấy ảnh.")
        proj = need_project()
        cfg = config()
        with conn_for() as conn:
            photo = conn.execute(
                "SELECT p.width, p.height, MIN(f.rel_path) AS rel FROM photos p "
                "JOIN files f ON f.sha256=p.sha256 AND f.last_seen_scan=? WHERE p.sha256=?",
                (db.current_scan_id(conn), sha),
            ).fetchone()
            if photo is None or photo["rel"] is None:
                raise _err(404, "Không tìm thấy ảnh.")
            boxes = conn.execute(
                "SELECT id, x, y, w, h FROM faces WHERE photo_sha256=?", (sha,)
            ).fetchall()
        cache = proj.dir / "thumbs" / "photos" / f"{sha}.jpg"
        try:
            if not cache.exists():
                imaging.make_preview(imaging.load_image(Path(cfg.input_dir) / photo["rel"]), cache)
            img = imaging.load_image(cache)
        except imaging.ImageError:
            raise _err(404, "Không đọc được ảnh.") from None
        scale = img.width / photo["width"] if photo["width"] else 1.0
        draw = ImageDraw.Draw(img)
        for b in boxes:
            hot = face is not None and b["id"] == face
            box = [b["x"] * scale, b["y"] * scale, (b["x"] + b["w"]) * scale, (b["y"] + b["h"]) * scale]
            draw.rectangle(box, outline=(255, 70, 70) if hot else (255, 255, 255), width=4 if hot else 2)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        return Response(buf.getvalue(), media_type="image/jpeg")

    # ------------------------------------------------------------ giao diện tĩnh
    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def find_free_port(start: int = 8765, tries: int = 30) -> int:
    import socket

    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise ProjectError(
        f"Các cổng từ {start} đến {start + tries - 1} đều đang bận. Hãy đóng chương trình đang dùng chúng."
    )
