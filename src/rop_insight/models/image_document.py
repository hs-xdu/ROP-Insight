"""Decoded original image and its metadata, independent of view transforms."""

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtGui import QImage


@dataclass(frozen=True)
class ImageDocument:
    path: Path
    image: QImage
    format: str
    file_sha256: str | None = None

    @property
    def resolution(self) -> str:
        return f"{self.image.width()} × {self.image.height()}"
