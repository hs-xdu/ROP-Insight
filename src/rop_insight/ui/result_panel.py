"""Compact layer controls and source-backed results; no synthetic defaults."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QComboBox, QLabel, QSlider,
                            QCheckBox, QProgressBar, QSizePolicy)

CLASSES = ("Normal", "Stage 1", "Stage 2", "Stage 3")
STATE_NAMES = {"pending": "等待", "running": "运行中", "success": "成功", "failed": "失败",
               "skipped": "跳过", "cancelled": "已取消"}
METRIC_NAMES = {"ridge_area_ratio_fov": "Ridge 面积比例", "ridge_solidity": "Ridge 实心度",
                "ridge_outer_vessel_density": "Ridge 外环血管密度", "ridge_max_radius_ratio": "Ridge 最大径向位置",
                "vessel_area_density_fov": "血管密度 VD", "fractal_dimension": "分形维数 FD",
                "sliding_window_max_density_gradient": "最大局部密度变化", "T3": "血管迂曲度 T3",
                "B3": "血管分支 B3", "S_median": "S_median"}


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
        self.metrics_label = QLabel("量化指标：未提供")
        self.metrics_label.setTextFormat(Qt.TextFormat.PlainText)
        self.metrics_label.setWordWrap(True)
        self.metrics_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.metrics_label)
        self.score_label = QLabel()
        self.auxiliary_label = QLabel()
        for label in (self.score_label, self.auxiliary_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            layout.addWidget(label)
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
        self.score_label.setText("连续严重程度评分：未提供")
        self.auxiliary_label.setText("RBF-SVM 辅助分类：未提供")
        self.metrics_label.setText("量化指标：未提供")
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
        self.score_label.setText("连续严重程度评分：未提供")
        self.auxiliary_label.setText("RBF-SVM 辅助分类：未提供")
        for result in run.modules.values():
            if result.state == "success" and result.output:
                score = result.output.values.get('score')
                if score:
                    self.score_label.setText(
                        f"连续严重程度评分：{score['median']:.6g}\n95%后验区间：[{score['lower']:.6g}, {score['upper']:.6g}]\n原后验相对评分，不对应临床分期"
                        if score['status'] == 'available' else f"连续严重程度评分：不可用 · {score['reason']}")
                auxiliary = result.output.values.get('auxiliary_classification')
                if auxiliary:
                    self.auxiliary_label.setText(
                        f"RBF-SVM 辅助分类：{auxiliary['prediction']}\n未校准概率；与 A6 独立展示"
                        if auxiliary['status'] == 'available' else f"RBF-SVM 辅助分类：不可用 · {auxiliary['reason']}")
            if result.state == "success" and result.output and "metrics" in result.output.values:
                self.metrics_label.setText("结构量化\n" + "\n".join(
                    f"{METRIC_NAMES.get(name,name)}：{metric['value']:.6g} {metric['unit']}（{metric['grid']}网格）" if metric['value'] is not None
                    else f"{METRIC_NAMES.get(name,name)}：不可用 · {metric['reason']}"
                    for name, metric in result.output.values['metrics'].items()))
        self.status.setText("\n".join(
            f"{name}：{STATE_NAMES[result.state]}"
            + ("（用户导入）" if result.output and result.output.values.get("source") == "user_imported_ridge" else "")
            + (f" · {result.error.message}" if result.error else "")
            for name, result in run.modules.items()))
        classifications = [r.output.classification for r in run.modules.values()
                           if r.state == "success" and r.output and r.output.classification is not None]
        if len(classifications) == 1:
            values = classifications[0].probabilities
            self.prediction.setText("A6 预测：" + CLASSES[max(range(4), key=lambda i: values[i])])
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
