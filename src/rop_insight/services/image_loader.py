"""Bounded image decoding without UI dependencies."""

from pathlib import Path
import hashlib

from PyQt6.QtCore import QFile, QIODevice
from PyQt6.QtGui import QImageReader

from rop_insight.models.image_document import ImageDocument


class ImageLoadError(ValueError):
    """A user-facing failure to load a supported image."""


class ImageLoader:
    def __init__(self, max_pixels: int = 40_000_000, memory_mb: int = 256):
        self.max_pixels = max_pixels
        # Qt's allocation limit is process-wide. Keep it bounded for all readers.
        QImageReader.setAllocationLimit(memory_mb)

    def load(self, path: str | Path) -> ImageDocument:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png"}:
            raise ImageLoadError("仅支持 JPG、JPEG 和 PNG 图像。")
        if not path.is_file():
            raise ImageLoadError("文件不存在或不是普通文件，请重新选择。")
        file = QFile(str(path))
        if not file.open(QIODevice.OpenModeFlag.ReadOnly):
            raise ImageLoadError("无法读取文件，请检查访问权限。")
        try:
            reader = QImageReader(file)
            reader.setDecideFormatFromContent(True)
            actual = bytes(reader.format()).decode("ascii", errors="replace").lower()
            expected = "png" if suffix == ".png" else "jpeg"
            if actual not in {"png", "jpeg", "jpg"}:
                raise ImageLoadError("文件不是有效的 JPEG 或 PNG 图像，或文件已损坏。")
            if ("jpeg" if actual == "jpg" else actual) != expected:
                raise ImageLoadError("文件扩展名与实际图像格式不一致。")
            size = reader.size()
            if not size.isValid():
                raise ImageLoadError("无法读取图像尺寸，文件可能已损坏。")
            if size.width() * size.height() > self.max_pixels:
                raise ImageLoadError(f"图像超过 {self.max_pixels:,} 像素的加载上限。")
            image = reader.read()
            if image.isNull():
                raise ImageLoadError("图像解码失败，文件可能损坏或超出内存限制。")
            if not file.seek(0):
                raise ImageLoadError("无法读取图像追溯信息。")
            digest = hashlib.sha256()
            while not file.atEnd():
                chunk = file.read(1024 * 1024)
                if not chunk and file.error() != QFile.FileError.NoError:
                    raise ImageLoadError("读取图像追溯信息失败。")
                digest.update(bytes(chunk))
            return ImageDocument(path.resolve(), image, expected.upper(), digest.hexdigest())
        finally:
            file.close()
