"""Single-image workflow and atomic state updates."""

from enum import Enum
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QVBoxLayout, QWidget, QScrollArea, QLayout, QSizePolicy,
)

from rop_insight.services.image_loader import ImageLoader, ImageLoadError
from rop_insight.ui.image_view import ImageView
from rop_insight.services.analysis_controller import AnalysisController
from rop_insight.services.analysis_config import ConfigError
from rop_insight.ui.result_panel import ResultPanel
from rop_insight.inference.imported_ridge import load_ridge
from rop_insight.services.result_exporter import ExportSnapshot, ExportError
from rop_insight.services.export_controller import ExportController
from rop_insight.services.report_builder import build_report
from rop_insight.services.report_exporter import export_report_bundle
from rop_insight.ui.report_dialog import ReportDialog
from rop_insight.ui.case_selector import CaseSelector
from rop_insight.ui.record_history import HistoryWindow
from rop_insight.services.local_records import record_job
from copy import deepcopy


class LoadState(Enum):
    EMPTY = "未加载"
    LOADING = "加载中"
    READY = "已加载"
    FAILED = "加载失败"


class MainWindow(QMainWindow):
    def __init__(self, loader=None, controller=None):
        super().__init__()
        self.loader = loader or ImageLoader()
        self.document = None
        self.state = LoadState.EMPTY
        self.analysis = controller if controller is not None else AnalysisController(parent=self)
        self.exporter = ExportController(self)
        self.report_exporter = ExportController(self,job=export_report_bundle)
        self.report_dialog = None
        self.library_root = None
        self.current_case = None
        self.case_dialog = None
        self.history_dialog = None
        self.run_cases = {}
        self.records_worker = ExportController(self,job=record_job)
        self.records_worker.changed.connect(self._update_analysis)
        self.records_worker.finished.connect(self._record_saved)
        self._closing = False
        self._display_run_id = None
        self._displayed_masks = {}
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
        header.addWidget(QLabel("本地研究原型 · 手动 Ridge"))
        layout.addLayout(header)
        body = QHBoxLayout()
        body.setSpacing(20)
        layout.addLayout(body, 1)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(250)
        side = QVBoxLayout(sidebar)
        # Content may grow vertically, but long filenames must never widen the panel.
        side.setSizeConstraints(QLayout.SizeConstraint.SetNoConstraint,
                                QLayout.SizeConstraint.SetMinimumSize)
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
        self.ridge_button = QPushButton("导入已有 Ridge Mask")
        self.ridge_button.clicked.connect(self.choose_ridge)
        side.addWidget(self.ridge_button)
        self.analyze_button = QPushButton("开始分析")
        self.cancel_analysis_button = QPushButton("取消分析")
        self.export_button = QPushButton("导出分析结果")
        self.export_button.clicked.connect(self.choose_export)
        self.report_button = QPushButton("预览辅助分析报告")
        self.report_button.clicked.connect(self.preview_report)
        self.analysis_label = QLabel("分析模块未配置")
        self.analysis_label.setWordWrap(True)
        self.analysis_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.analysis_label.setTextFormat(Qt.TextFormat.PlainText)
        side.addWidget(self.analyze_button)
        side.addWidget(self.cancel_analysis_button)
        side.addWidget(self.export_button)
        side.addWidget(self.report_button)
        self.case_button = QPushButton("病例与资料库")
        self.case_button.clicked.connect(self.choose_case)
        side.addWidget(self.case_button)
        self.case_label = QLabel("临时分析 · 未选择病例")
        self.case_label.setTextFormat(Qt.TextFormat.PlainText)
        self.case_label.setWordWrap(True)
        self.case_label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        side.addWidget(self.case_label)
        self.save_record_button = QPushButton("保存分析记录")
        self.save_record_button.clicked.connect(self.save_record)
        side.addWidget(self.save_record_button)
        self.history_button = QPushButton("历史分析记录")
        self.history_button.clicked.connect(self.open_history)
        side.addWidget(self.history_button)
        side.addWidget(self.analysis_label)
        self.analyze_button.clicked.connect(self.start_analysis)
        self.cancel_analysis_button.clicked.connect(self.analysis.cancel)
        self.analysis.changed.connect(self._update_analysis)
        self.exporter.changed.connect(self._update_analysis)
        self.exporter.finished.connect(self._export_finished)
        self.report_exporter.changed.connect(self._update_analysis)
        self.report_exporter.finished.connect(self._report_export_finished)
        self.analysis.idle.connect(self._analysis_idle)
        self.result_panel = ResultPanel()
        side.addWidget(self.result_panel)
        self.result_panel.layers_changed.connect(self._change_layers)
        self.analysis.result_changed.connect(self._show_results)
        side.addSpacing(12)
        self.name_label = QLabel("—")
        self.name_label.setWordWrap(True)
        self.name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
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
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setFixedWidth(270)
        sidebar_scroll.setWidget(sidebar)
        body.addWidget(sidebar_scroll)
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
        self._update_analysis()
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
        self.ridge_button.setEnabled(self.document is not None and not self._closing)
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
        self.analysis.set_document(document)
        self.name_label.setText(document.path.name)
        self.name_label.setToolTip(str(document.path))
        self.resolution_label.setText(document.resolution + " px")
        self.format_label.setText(document.format)
        self.state = LoadState.READY
        self._update_controls()
        self.statusBar().showMessage(f"已加载 · {document.path.name}")
        return True

    def clear_image(self):
        self.analysis.set_document(None)
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

    def start_analysis(self):
        if self._closing or self._records_busy():
            return
        try:
            if self.analysis.start():
                self.run_cases = {self.analysis.current_run.run_id:(self.library_root,deepcopy(self.current_case))}
                self._update_analysis()
        except ConfigError as exc:
            self.analysis_label.setText(f"分析配置错误：{exc}")

    def choose_export(self):
        parent = QFileDialog.getExistingDirectory(self, "选择成果保存位置（叠加图包含眼底影像）")
        if parent:
            self.export_results(parent)

    def preview_report(self):
        if self.analysis.busy or self.report_exporter.busy or self._closing:
            return None
        try:
            report=build_report(ExportSnapshot.capture(self.analysis.context,self.analysis.current_run))
        except (ExportError,ValueError) as exc:
            self.error_label.setText(f"报告生成失败：{exc}");self.error_label.show()
            return None
        self.error_label.hide()
        if self.report_dialog is None:
            self.report_dialog=ReportDialog(report,self.report_exporter,self.export_report,self)
        else:self.report_dialog.set_report(report)
        self.report_dialog.show();self.report_dialog.raise_()
        return self.report_dialog

    def export_report(self,report,parent):
        if self.report_exporter.busy or self.records_worker.busy or self._closing:return False
        return self.report_exporter.start(report,parent)

    def _report_export_finished(self,path,error):
        self.statusBar().showMessage(error if error else f"PDF报告已导出 · {path}")
        if self._closing and not self.analysis.busy and not self.exporter.busy and not self._records_busy():self.close()

    def export_results(self, parent):
        if self.exporter.busy or self.analysis.busy or self._closing:
            return False
        try:
            snapshot = ExportSnapshot.capture(self.analysis.context,self.analysis.current_run)
        except ExportError as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()
            return False
        self.error_label.hide()
        self.statusBar().showMessage("正在导出分析快照…")
        return self.exporter.start(snapshot,parent)

    def _export_finished(self, path, error):
        if error:
            self.error_label.setText(error)
            self.error_label.show()
            self.statusBar().showMessage(error)
        else:
            self.statusBar().showMessage(f"已导出分析快照 · {path}")
        if self._closing and not self.analysis.busy and not self.report_exporter.busy and not self._records_busy():
            self.close()

    def choose_ridge(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入与当前原图对应的 Ridge Mask", "", "二值 PNG (*.png *.PNG)")
        if path:
            self.import_ridge(path)

    def import_ridge(self, path):
        if self.document is None:
            return False
        try:
            output = load_ridge(path, self.document.image.size())
            self.analysis.provide_input("ridge", output)
        except (ValueError, OSError) as exc:
            self.error_label.setText(f"Ridge Mask 导入失败：{exc}")
            self.error_label.show()
            return False
        self.error_label.hide()
        self.ridge_button.setText("重新导入 Ridge Mask")
        self.ridge_button.setToolTip("用户提供的 Ridge Mask：" + str(path))
        return True

    def _records_busy(self):
        return self.records_worker.busy or (self.case_dialog is not None and self.case_dialog.worker.busy) or (self.history_dialog is not None and self.history_dialog.worker.busy)

    def open_history(self):
        if self._closing:return None
        if self.history_dialog is None:
            self.history_dialog=HistoryWindow(self.library_root,self)
            self.history_dialog.worker.finished.connect(lambda *_:self._analysis_idle())
        self.history_dialog._closing=False
        self.history_dialog.show();self.history_dialog.raise_()
        return self.history_dialog

    def choose_case(self):
        if self.analysis.busy or self._records_busy() or self._closing:return None
        if self.case_dialog is not None:self.case_dialog.close()
        self.case_dialog=CaseSelector(self.library_root,self.current_case,self)
        self.case_dialog.selected.connect(self.apply_case)
        self.case_dialog.worker.changed.connect(self._update_analysis)
        self.case_dialog.worker.finished.connect(lambda *_:self._analysis_idle())
        self.case_dialog.show()
        return self.case_dialog

    def apply_case(self,root,case):
        if self.analysis.busy or self.records_worker.busy or self._closing:return False
        self.library_root=str(root) if root else None;self.current_case=deepcopy(case)
        self._update_analysis()
        return True

    def _record_saved(self,result,error):
        if error or not result['ok']:
            self.error_label.setText('保存记录失败：'+(error or result['message']));self.error_label.show()
        else:
            report='含报告' if result['record']['report_path'] else '报告未生成，可预览后再次保存补充'
            self.error_label.hide()
            self.statusBar().showMessage('分析记录已保存（'+report+'） · '+result['root'])
        self._analysis_idle()

    def save_record(self):
        run=self.analysis.current_run
        if self._closing or self.analysis.busy or self.report_exporter.busy or self._records_busy() or run is None:return False
        binding=self.run_cases.get(run.run_id)
        if not binding or binding!=(self.library_root,self.current_case) or self.current_case is None:
            self.error_label.setText('请先选择病例并重新开始分析；已有结果不能改挂到其他病例。');self.error_label.show();return False
        try:snapshot=ExportSnapshot.capture(self.analysis.context,run)
        except ValueError as error:self.error_label.setText(str(error));self.error_label.show();return False
        report=None
        if self.report_dialog is not None:
            candidate=self.report_dialog.report
            source=candidate.data['source']
            if source['run']['run_id']==run.run_id and source['image']['image_id']==snapshot.context.image_id:report=candidate
        job=dict(kind='save',root=self.library_root,case=deepcopy(self.current_case),snapshot=snapshot,report=report)
        self.statusBar().showMessage('正在后台保存原图、分析结果及已有报告…')
        return self.records_worker.start(job,None)

    def _update_analysis(self):
        run = self.analysis.current_run
        busy=self._records_busy()
        self.history_button.setEnabled(not self._closing)
        self.case_button.setEnabled(not self.analysis.busy and not busy and not self._closing)
        self.case_label.setText(f"当前病例：{self.current_case['case_code']} · "+{'left':'左眼','right':'右眼','unspecified':'未指定'}[self.current_case['eye']] if self.current_case else "临时分析 · 未选择病例")
        if self.current_case:self.case_label.setText(self.case_label.text()+' · '+(self.current_case['exam_date'] or '日期未填写'))
        bound=self.run_cases.get(run.run_id) if run else None
        if bound and bound!=(self.library_root,self.current_case) and bound[1]:
            self.case_label.setText(self.case_label.text()+'\n当前结果属于：'+bound[1]['case_code']+'；请重新分析后保存。')
        self.save_record_button.setEnabled(bool(run and run.finished_at and self.current_case and bound==(self.library_root,self.current_case)) and not self.analysis.busy and not self.report_exporter.busy and not busy and not self._closing)
        self.report_button.setEnabled(bool(run and run.finished_at and run.status!='running')
            and not self.analysis.busy and not self.report_exporter.busy and not self._closing)
        self.export_button.setEnabled(bool(run and run.finished_at and run.status != 'running')
            and not self.analysis.busy and not self.exporter.busy and not self._closing)
        run_id = self.analysis.current_run.run_id if self.analysis.current_run else None
        if run_id != self._display_run_id or run_id is None:
            if self.report_dialog is not None:self.report_dialog.close()
            self._display_run_id = run_id
            self._displayed_masks.clear()
            self.view.clear_results()
            self.result_panel.reset()
            for output in self.analysis.input_outputs.values():
                for mask in output.masks:
                    self.view.set_mask(mask)
                    self._displayed_masks[mask.structure] = mask
            self.result_panel.set_available(set(self._displayed_masks))
            if not self.analysis.input_outputs:
                self.ridge_button.setText("导入已有 Ridge Mask")
                self.ridge_button.setToolTip("")
        self.analyze_button.setEnabled(
            self.analysis.context is not None and self.analysis.available
            and not self.analysis.busy and not self._records_busy() and not self._closing)
        self.cancel_analysis_button.setEnabled(self.analysis.busy and not self.analysis.cancelling)
        if self._closing:
            text = "正在等待分析任务安全退出…"
        elif self.analysis.cancelling:
            text = "正在取消，等待当前模块退出…"
        elif self.analysis.busy:
            text = "分析中…"
        elif self.analysis.current_run:
            text = {"success": "分析完成", "partial_success": "分析部分完成",
                    "failed": "分析失败", "cancelled": "分析已取消"}.get(
                        self.analysis.current_run.status, "分析中…")
            failures = [f"{result.module_id}：{result.error.message}"
                        for result in self.analysis.current_run.modules.values()
                        if result.error and result.state == "failed"]
            if failures:
                text += "\n" + "\n".join(failures)
        elif not self.analysis.available:
            needs_input = any(m.enabled and getattr(self.analysis.registry.get(m.adapter_id), "requires_input", False)
                              and m.module_id not in self.analysis.input_outputs for m in self.analysis.config.modules)
            text = "请导入对应原图的 Ridge Mask" if needs_input else "分析模块未配置"
        else:
            text = "可以开始分析" if self.analysis.context else "请先导入图像"
        self.analysis_label.setText(text)

    def _show_results(self, run):
        if (self.analysis.context is None or self.analysis.current_run is None
                or (run.image_id, run.run_id) != (self.analysis.context.image_id, self.analysis.current_run.run_id)):
            return
        if self._display_run_id != run.run_id:
            self._display_run_id = run.run_id
            self._displayed_masks.clear()
            self.view.clear_results()
            self.result_panel.reset()
        for result in run.modules.values():
            if result.state == "success" and result.output:
                for mask in result.output.masks:
                    if self._displayed_masks.get(mask.structure) != mask:
                        self.view.set_mask(mask)
                        self._displayed_masks[mask.structure] = mask
        self.result_panel.set_available(set(self._displayed_masks))
        self.result_panel.show_run(run)

    def _change_layers(self):
        self.view.display_mode = self.result_panel.mode.currentData()
        self.view.overlay_opacity = self.result_panel.opacity.value() / 100
        self.view.overlay_enabled = {name: check.isChecked() for name, check in self.result_panel.checks.items()}
        self.view.update_layers()

    def closeEvent(self, event):
        if self.analysis.busy or self.exporter.busy or self.report_exporter.busy or self._records_busy():
            self._closing = True
            self.import_button.setEnabled(False)
            self.clear_button.setEnabled(False)
            self.ridge_button.setEnabled(False)
            self.export_button.setEnabled(False)
            self._update_analysis()
            self.analysis.cancel()
            if self.history_dialog is not None:self.history_dialog.close()
            event.ignore()
        else:
            if self.case_dialog is not None:self.case_dialog.close()
            if self.history_dialog is not None:self.history_dialog.close()
            event.accept()

    def _analysis_idle(self):
        if self._closing and not self.analysis.busy and not self.exporter.busy and not self.report_exporter.busy and not self._records_busy():
            self.close()
