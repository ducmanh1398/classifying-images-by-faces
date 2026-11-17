"""Đọc ảnh, xoay theo EXIF, cắt thumbnail, ảnh xem trước (đặc tả mục 5)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

FACE_THUMB_SIZE = 160
FACE_MARGIN = 0.30
PREVIEW_SIZE = 1280

_heif_registered = False


class ImageError(Exception):
    """Không đọc được ảnh."""


def _register_heif() -> None:
    global _heif_registered
    if not _heif_registered:
        import pillow_heif

        pillow_heif.register_heif_opener()
        _heif_registered = True


def load_image(path: Path | str) -> Image.Image:
    """Mở ảnh bằng Pillow (đường dẫn Unicode ổn), xoay theo EXIF, chuyển RGB."""
    try:
        _register_heif()
        with Image.open(path) as im:
            im.load()
            im = ImageOps.exif_transpose(im)
            return im.convert("RGB")
    except Exception as e:  # Pillow ném nhiều loại lỗi khác nhau
        raise ImageError(f"{Path(path).name}: {e}") from e


def crop_face(img: Image.Image, x: float, y: float, w: float, h: float) -> Image.Image:
    """Cắt mặt, nới 30% mỗi phía, thu về cạnh dài 160 px."""
    mx, my = w * FACE_MARGIN, h * FACE_MARGIN
    box = (
        max(0, int(x - mx)),
        max(0, int(y - my)),
        min(img.width, int(x + w + mx)),
        min(img.height, int(y + h + my)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        box = (0, 0, img.width, img.height)
    c = img.crop(box)
    c.thumbnail((FACE_THUMB_SIZE, FACE_THUMB_SIZE))
    return c


def save_face_thumb(img: Image.Image, x, y, w, h, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    crop_face(img, x, y, w, h).save(dest, "JPEG", quality=88)


def make_preview(img: Image.Image, dest: Path, size: int = PREVIEW_SIZE) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    p = img.copy()
    p.thumbnail((size, size))
    p.save(dest, "JPEG", quality=85)
