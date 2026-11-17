import pytest
from PIL import Image

from facesort.imaging import ImageError, crop_face, load_image, make_preview, save_face_thumb


def test_exif_rotation_applied(tmp_path):
    im = Image.new("RGB", (40, 20), (255, 0, 0))
    exif = Image.Exif()
    exif[0x0112] = 6  # xoay 90 độ
    p = tmp_path / "r.jpg"
    im.save(p, exif=exif)
    assert load_image(p).size == (20, 40)


def test_png_rgba_to_rgb(tmp_path):
    p = tmp_path / "a.png"
    Image.new("RGBA", (10, 10), (1, 2, 3, 128)).save(p)
    assert load_image(p).mode == "RGB"


def test_heic(tmp_path):
    import pillow_heif

    pillow_heif.register_heif_opener()
    p = tmp_path / "ảnh.heic"
    Image.new("RGB", (64, 48), (10, 200, 30)).save(p, format="HEIF")
    assert load_image(p).size == (64, 48)


def test_vietnamese_path(tmp_path):
    d = tmp_path / "Ảnh cưới" / "Họ hàng"
    d.mkdir(parents=True)
    p = d / "ảnh đẹp.jpg"
    Image.new("RGB", (10, 10)).save(p)
    assert load_image(p).size == (10, 10)


def test_corrupt_file(tmp_path):
    p = tmp_path / "bad.jpg"
    p.write_bytes(b"not an image")
    with pytest.raises(ImageError):
        load_image(p)


def test_missing_file(tmp_path):
    with pytest.raises(ImageError):
        load_image(tmp_path / "nope.jpg")


def test_face_crop_margin_and_size(tmp_path):
    im = Image.new("RGB", (1000, 800))
    c = crop_face(im, 400, 300, 100, 100)
    assert max(c.size) <= 160
    dest = tmp_path / "t" / "1.jpg"
    save_face_thumb(im, 400, 300, 100, 100, dest)
    assert dest.exists()


def test_face_crop_clamped_at_border():
    im = Image.new("RGB", (100, 100))
    assert crop_face(im, 0, 0, 50, 50).size[0] > 0


def test_preview_max_side(tmp_path):
    im = Image.new("RGB", (4000, 2000))
    d = tmp_path / "p.jpg"
    make_preview(im, d)
    assert max(Image.open(d).size) == 1280
