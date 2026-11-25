"""Compact layer controls and source-backed results; no synthetic defaults."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QComboBox, QLabel, QSlider,
                            QCheckBox, QProgressBar, QSizePolicy)

CLASSES = ("Normal", "Stage 1", "Stage 2", "Stage 3")
STATE_NAMES = {"pending": "等待", "running": "运行中", "success": "成功", "failed": "失败",
               "skipped": "跳过", "cancelled": "已取消"}


class ResultPanel(QWidget):
    layers_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("结果与图层"))
        self.mode = QComboBox()
        for title, value in (("原始图像", "original"), ("Ridge Mask", "ridge"),
                             ("Vessel Mask", "vessel"), ("叠加显示", "overlay")):
            self.mode.addItem(title, value)
        self.mode.setMinimumWidth(0)
        self.mode.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.mode)
        self.checks = {}
        for name in ("ridge", "vessel"):
            check = QCheckBox(name.capitalize() + " 叠加")
            check.setChecked(True)
            check.toggled.connect(self.layers_changed)
            layout.addWidget(check)
            self.checks[name] = check
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(50)
        self.opacity_label = QLabel("叠加透明度：50%")
        layout.addWidget(self.opacity_label)
        layout.addWidget(self.opacity)
        self.opacity.valueChanged.connect(self._opacity_changed)
        self.mode.currentIndexChanged.connect(self.layers_changed)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.status)
        self.prediction = QLabel()
        layout.addWidget(self.prediction)
        self.bars = []
        for name in CLASSES:
            layout.addWidget(QLabel(name))
            bar = QProgressBar()
            bar.setRange(0, 1000)
            layout.addWidget(bar)
            self.bars.append(bar)
        self.reset()

    def _opacity_changed(self, value):
        self.opacity_label.setText(f"叠加透明度：{value}%")
        self.layers_changed.emit()

    def reset(self):
        self.status.setText("暂无分析结果")
        self.prediction.setText("分期：未提供")
        for bar in self.bars:
            bar.setValue(0)
            bar.setFormat("未提供")
            bar.setEnabled(False)
        self.set_available(set())
        self.mode.setCurrentIndex(0)

    def set_available(self, structures):
        for index in (1, 2):
            self.mode.model().item(index).setEnabled(self.mode.itemData(index) in structures)
        self.mode.model().item(3).setEnabled(bool(structures))
        for name, check in self.checks.items():
            check.setEnabled(name in structures)
        self.opacity.setEnabled(bool(structures))
        if self.mode.currentData() not in ("original", "overlay") and self.mode.currentData() not in structures:
            self.mode.setCurrentIndex(0)

    def show_run(self, run):
        self.status.setText("\n".join(
            f"{name}：{STATE_NAMES[result.state]}"
            + ("（用户导入）" if result.output and result.output.values.get("source") == "user_imported_ridge" else "")
            + (f" · {result.error.message}" if result.error else "")
            for name, result in run.modules.items()))
        classifications = [r.output.classification for r in run.modules.values()
                           if r.state == "success" and r.output and r.output.classification is not None]
        if len(classifications) == 1:
            values = classifications[0].probabilities
            self.prediction.setText("预测：" + CLASSES[max(range(4), key=lambda i: values[i])])
            for bar, value in zip(self.bars, values):
                bar.setEnabled(True)
                bar.setValue(round(value * 1000))
                bar.setFormat(f"{value:.1%}")
        elif len(classifications) > 1:
            self.prediction.setText("分期：结果来源冲突")
            for bar in self.bars:
                bar.setValue(0)
                bar.setFormat("未提供")
                bar.setEnabled(False)
