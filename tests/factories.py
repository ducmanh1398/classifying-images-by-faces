"""Bộ dựng dữ liệu giả: ảnh, mặt, cụm, nhãn trong DB tạm và file nhỏ trên đĩa."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from facesort import db
from facesort.config import Config
from facesort.export import make_plan, run_export
from facesort.labels import get_or_create_label
from facesort.scan import sha256_file


def tiny_png(seed: int) -> bytes:
    img = Image.new("RGB", (8, 8), (seed % 256, (seed * 7) % 256, (seed * 13) % 256))
    img.putpixel((0, 0), ((seed >> 8) % 256, seed % 256, 1))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class World:
    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.input_dir = tmp_path / "Ảnh cưới gốc"
        self.output_dir = tmp_path / "Đầu ra"
        self.input_dir.mkdir()
        self.config = Config(input_dir=str(self.input_dir), output_dir=str(self.output_dir))
        self.conn = db.connect(tmp_path / "test.db")
        db.set_meta(self.conn, "scan_id", "1")
        self.conn.commit()

    # --- dựng dữ liệu
    def add_photo(self, rel: str, seed: int = 0, status: str = "done") -> str:
        """Ghi file ảnh nhỏ; cùng seed thì nội dung giống hệt nhau (file trùng)."""
        path = self.input_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(tiny_png(seed))
        st = path.stat()
        sha = sha256_file(path)
        self.conn.execute(
            "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, 1)",
            (rel, st.st_size, st.st_mtime_ns, sha),
        )
        canon = self.conn.execute(
            "SELECT MIN(rel_path) FROM files WHERE sha256=?", (sha,)
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO photos (sha256, canonical_path, status) VALUES (?, ?, ?) "
            "ON CONFLICT(sha256) DO UPDATE SET canonical_path=excluded.canonical_path",
            (sha, canon, status),
        )
        self.conn.commit()
        return sha

    def label(self, name: str) -> int:
        return get_or_create_label(self.conn, name, self.config.unlabeled_folder)

    def cluster(self, label: str | None = None, ignored: bool = False) -> int:
        lid = self.label(label) if label else None
        cur = self.conn.execute(
            "INSERT INTO clusters (label_id, ignored) VALUES (?, ?)", (lid, int(ignored))
        )
        self.conn.commit()
        return cur.lastrowid

    def face(
        self,
        sha: str,
        cluster: int | None = None,
        label: str | None = None,
        quality_ok: bool = True,
        ignored: bool = False,
    ) -> int:
        lid = self.label(label) if label else None
        cur = self.conn.execute(
            "INSERT INTO faces (photo_sha256, x, y, w, h, det_score, quality_ok, cluster_id, "
            "label_id, ignored) VALUES (?, 0, 0, 10, 10, 0.9, ?, ?, ?, ?)",
            (sha, int(quality_ok), cluster, lid, int(ignored)),
        )
        self.conn.commit()
        return cur.lastrowid

    # --- thao tác
    def plan(self):
        return make_plan(self.conn, self.config)

    def export(self, dry_run: bool = False):
        return run_export(self.conn, self.config, dry_run=dry_run)

    def folder_files(self, folder: str) -> list[str]:
        d = self.output_dir / folder
        return sorted(p.name for p in d.iterdir()) if d.exists() else []

    def folder_hashes(self, folder: str) -> list[str]:
        d = self.output_dir / folder
        return sorted(sha256_file(p) for p in d.iterdir())
