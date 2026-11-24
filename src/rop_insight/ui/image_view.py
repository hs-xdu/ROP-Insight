"""Image-space rendering with independent zoom and pan state."""

import math

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QGraphicsScene, QGraphicsView


class ImageView(QGraphicsView):
    zoom_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.item = None
        self.fit_mode = True
        self.min_scale = 0.01
        self.max_scale = 32.0
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(self.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(self.ViewportAnchor.AnchorViewCenter)
        # Fixed scrollbar policies avoid fitInView / resize recursion.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(self.DragMode.NoDrag)
        self.setBackgroundBrush(Qt.GlobalColor.transparent)
        self.setFrameShape(self.Shape.NoFrame)

    @property
    def scale_factor(self):
        return self.transform().m11()

    def set_image(self, image):
        self.clear_image()
        self.item = self.scene().addPixmap(QPixmap.fromImage(image))
        self.setSceneRect(self.item.boundingRect())
        self.setDragMode(self.DragMode.ScrollHandDrag)
        self.fit_image()

    def clear_image(self):
        self.scene().clear()
        self.item = None
        self.resetTransform()
        self.setSceneRect(0, 0, 0, 0)
        self.fit_mode = True
        self.setDragMode(self.DragMode.NoDrag)
        self.zoom_changed.emit(0.0)
        self.viewport().update()

    def fit_image(self):
        if self.item is None:
            return
        self.fit_mode = True
        self.resetTransform()
        self.fitInView(self.item, Qt.AspectRatioMode.KeepAspectRatio)
        # Even a huge source image must be able to fit fully in the viewport.
        self.min_scale = min(0.01, self.scale_factor)
        self.max_scale = max(32.0, self.scale_factor)
        self.centerOn(self.item)
        self.zoom_changed.emit(self.scale_factor)

    def zoom(self, factor):
        if self.item is None or not math.isfinite(factor) or factor <= 0:
            return
        self.fit_mode = False
        target = max(self.min_scale, min(self.max_scale, self.scale_factor * factor))
        self.scale(target / self.scale_factor, target / self.scale_factor)
        self.zoom_changed.emit(self.scale_factor)

    def wheelEvent(self, event):
        if self.item is not None:
            steps = max(-10, min(10, event.angleDelta().y() / 120))
            self.zoom(1.2 ** steps)
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit_image()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self.item is None:
            painter.save()
            painter.resetTransform()
            painter.setPen(Qt.GlobalColor.lightGray)
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter,
                             "尚未导入图像\n\n点击左侧「导入图像」开始查看")
            painter.restore()
