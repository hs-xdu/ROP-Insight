import pytest
from PyQt6.QtGui import QColor, QImage


@pytest.fixture
def image_file(tmp_path):
    def create(name="眼底.png", width=1200, height=800, fmt="PNG"):
        path = tmp_path / name
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor("#d36b36"))
        assert image.save(str(path), fmt)
        return path
    return create
