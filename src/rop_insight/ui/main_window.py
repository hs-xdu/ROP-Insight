"""Single-image workflow and atomic state updates."""

from enum import Enum
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QVBoxLayout, QWidget,
)

from rop_insight.services.image_loader import ImageLoader, ImageLoadError
from rop_insight.ui.image_view import ImageView


class LoadState(Enum):
    EMPTY = "未加载"
    LOADING = "加载中"
    READY = "已加载"
    FAILED = "加载失败"


class MainWindow(QMainWindow):
    def __init__(self, loader=None):
        super().__init__()
        self.loader = loader or ImageLoader()
        self.document = None
        self.state = LoadState.EMPTY
        self.setWindowTitle("ROP-Insight · 眼底图像工作台")
        self.resize(1180, 780)
        self.setMinimumSize(800, 560)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 12)
        header = QHBoxLayout()
        title = QLabel("ROP-Insight")
        title.setObjectName("brand")
        header.addWidget(title)
        header.addWidget(QLabel("眼底图像工作台"))
        header.addStretch()
        header.addWidget(QLabel("本地查看  ·  MVP 0.1"))
        layout.addLayout(header)
        body = QHBoxLayout()
        body.setSpacing(20)
        layout.addLayout(body, 1)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(250)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 22, 18, 22)
        side.setSpacing(14)
        side.addWidget(QLabel("图像管理"))
        self.import_button = QPushButton("导入图像")
        self.import_button.setObjectName("primary")
        self.import_button.clicked.connect(self.choose_image)
        side.addWidget(self.import_button)
        side.addWidget(QLabel("支持 JPG / JPEG / PNG"))
        self.clear_button = QPushButton("清除图像")
        self.clear_button.clicked.connect(self.clear_image)
        side.addWidget(self.clear_button)
        side.addSpacing(12)
        self.name_label = QLabel("—")
        self.name_label.setWordWrap(True)
        self.name_label.setTextFormat(Qt.TextFormat.PlainText)
        self.resolution_label = QLabel("—")
        self.format_label = QLabel("—")
        for caption, label in (("文件名称", self.name_label),
                               ("图像分辨率", self.resolution_label),
                               ("文件格式", self.format_label)):
            side.addWidget(QLabel(caption))
            label.setObjectName("value")
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            side.addWidget(label)
        side.addStretch()
        hint = QLabel("滚轮缩放 · 按住鼠标左键拖动\n点击「适应窗口」查看完整图像")
        hint.setWordWrap(True)
        side.addWidget(hint)
        body.addWidget(sidebar)
        viewer_column = QVBoxLayout()
        body.addLayout(viewer_column, 1)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("原始图像"))
        controls.addStretch()
        self.zoom_label = QLabel("—")
        controls.addWidget(self.zoom_label)
        self.zoom_out_button = QPushButton("缩小 −")
        self.zoom_in_button = QPushButton("放大 +")
        self.fit_button = QPushButton("适应窗口")
        for button in (self.zoom_out_button, self.zoom_in_button, self.fit_button):
            controls.addWidget(button)
        viewer_column.addLayout(controls)
        self.view = ImageView()
        self.view.setObjectName("imageView")
        viewer_column.addWidget(self.view, 1)
        self.error_label = QLabel()
        self.error_label.setObjectName("error")
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        viewer_column.addWidget(self.error_label)
        self.zoom_out_button.clicked.connect(lambda: self.view.zoom(1 / 1.2))
        self.zoom_in_button.clicked.connect(lambda: self.view.zoom(1.2))
        self.fit_button.clicked.connect(self.view.fit_image)
        self.view.zoom_changed.connect(
            lambda scale: self.zoom_label.setText(f"{scale:.0%}" if scale else "—"))
        action = QAction("导入图像", self)
        action.setShortcut(QKeySequence.StandardKey.Open)
        action.triggered.connect(self.choose_image)
        self.addAction(action)
        self._update_controls()
        self.statusBar().showMessage("未加载 · 请选择一张眼底图像")
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #f3f6fa; color: #334155;
                font-family: 'Microsoft YaHei UI'; font-size: 13px; }
            QLabel#brand { font-size: 25px; font-weight: 700; color: #0f766e; }
            QFrame#sidebar { background: white; border-radius: 12px; }
            QFrame#sidebar QLabel { background: transparent; }
            QLabel#value { color: #0f172a; font-weight: 600; }
            QPushButton { background: white; border: 1px solid #cbd5e1;
                border-radius: 6px; padding: 9px 13px; }
            QPushButton:hover { background: #e2e8f0; }
            QPushButton:disabled { color: #94a3b8; border-color: #e2e8f0; }
            QPushButton#primary { background: #0f766e; color: white; border: none; }
            QPushButton#primary:hover { background: #115e59; }
            QGraphicsView#imageView { background: #101b2a; border-radius: 10px; }
            QLabel#error { background: #fff1f2; color: #be123c; padding: 12px; }
            QStatusBar { background: #f3f6fa; color: #64748b; }
        """)

    def _update_controls(self):
        for control in (self.clear_button, self.zoom_in_button,
                        self.zoom_out_button, self.fit_button):
            control.setEnabled(self.document is not None)
        self.import_button.setText("重新选择图像" if self.document else "导入图像")

    def choose_image(self):
        start = str(self.document.path.parent) if self.document else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择眼底图像", start,
            "眼底图像 (*.jpg *.jpeg *.png *.JPG *.JPEG *.PNG)")
        if path:
            self.load_image(path)

    def load_image(self, path: str | Path) -> bool:
        self.state = LoadState.LOADING
        self.statusBar().showMessage("加载中 · 正在读取图像…")
        self.statusBar().repaint()
        self.error_label.hide()
        try:
            document = self.loader.load(path)
        except (ImageLoadError, OSError) as exc:
            self.state = LoadState.FAILED
            message = f"加载失败：{exc}"
            if self.document:
                message += " 当前仍显示上一张成功加载的图像。"
            self.error_label.setText(message)
            self.error_label.show()
            self.statusBar().showMessage(message)
            return False
        self.view.set_image(document.image)
        self.document = document
        self.name_label.setText(document.path.name)
        self.name_label.setToolTip(str(document.path))
        self.resolution_label.setText(document.resolution + " px")
        self.format_label.setText(document.format)
        self.state = LoadState.READY
        self._update_controls()
        self.statusBar().showMessage(f"已加载 · {document.path.name}")
        return True

    def clear_image(self):
        self.document = None
        self.view.clear_image()
        self.name_label.setText("—")
        self.name_label.setToolTip("")
        self.resolution_label.setText("—")
        self.format_label.setText("—")
        self.error_label.clear()
        self.error_label.hide()
        self.state = LoadState.EMPTY
        self._update_controls()
        self.statusBar().showMessage("未加载 · 请选择一张眼底图像")
