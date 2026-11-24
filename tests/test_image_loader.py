import pytest
from PyQt6.QtCore import QFile

from rop_insight.services.image_loader import ImageLoader, ImageLoadError


@pytest.mark.parametrize("name,fmt,expected", [
    ("眼底.png", "PNG", "PNG"), ("eye.JPG", "JPEG", "JPEG"),
    ("eye.JpEg", "JPEG", "JPEG"),
])
def test_supported_images_and_metadata(image_file, name, fmt, expected):
    path = image_file(name, 123, 87, fmt)
    before = path.read_bytes()
    document = ImageLoader().load(path)
    assert document.path == path.resolve()
    assert document.resolution == "123 × 87"
    assert document.format == expected
    assert not document.image.isNull()
    assert path.read_bytes() == before


def test_bad_files(tmp_path, image_file):
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not an image")
    disguised = image_file("fake.jpg", fmt="PNG")
    gif = image_file("fake.png", fmt="BMP")
    for path in (bad, disguised, gif, tmp_path / "missing.png", tmp_path / "file.txt"):
        with pytest.raises(ImageLoadError):
            ImageLoader().load(path)


def test_pixel_limit(image_file):
    with pytest.raises(ImageLoadError, match="像素"):
        ImageLoader(max_pixels=100).load(image_file(width=11, height=10))


def test_permission_error(image_file, monkeypatch):
    path = image_file()
    monkeypatch.setattr(QFile, "open", lambda *_: False)
    with pytest.raises(ImageLoadError, match="权限"):
        ImageLoader().load(path)


def test_truncated_decode_is_rejected(image_file):
    path = image_file()
    path.write_bytes(path.read_bytes()[:50])
    with pytest.raises(ImageLoadError):
        ImageLoader().load(path)
