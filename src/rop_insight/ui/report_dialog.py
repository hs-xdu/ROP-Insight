"""Read-only report snapshot with shared rendering and an atomic PDF export."""

from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QTextBrowser,QTabWidget,QPushButton,QLabel,QFileDialog
from rop_insight.services.report_template import render_html,STYLESHEET


class ReportDialog(QDialog):
    def __init__(self,report,exporter,export_callback,parent=None):
        super().__init__(parent)
        self.exporter,self.export_callback=exporter,export_callback
        self._closing=False
        self.resize(900,760);self.setMinimumSize(620,480)
        layout=QVBoxLayout(self)
        self.identity=QLabel();self.identity.setTextFormat(Qt.TextFormat.PlainText)
        self.identity.setWordWrap(True);layout.addWidget(self.identity)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        self.browsers=[]
        for title in ('简要报告','详细报告 / PDF内容'):
            browser=QTextBrowser();browser.setOpenLinks(False);browser.setOpenExternalLinks(False)
            browser.document().setDefaultFont(QFont('Microsoft YaHei',10))
            browser.document().setDefaultStyleSheet(STYLESHEET)
            self.tabs.addTab(browser,title);self.browsers.append(browser)
        controls=QHBoxLayout();layout.addLayout(controls)
        self.status=QLabel('PDF导出包含详细报告、精确数值JSON及来源关联。')
        self.status.setWordWrap(True);controls.addWidget(self.status,1)
        self.export_button=QPushButton('导出PDF报告');self.export_button.clicked.connect(self.choose_export)
        controls.addWidget(self.export_button)
        self.close_button=QPushButton('关闭');self.close_button.clicked.connect(self.close);controls.addWidget(self.close_button)
        self.exporter.changed.connect(self.update_busy)
        self.exporter.finished.connect(self.export_finished)
        self.set_report(report)

    def set_report(self,report):
        self.report=report;self._closing=False
        data=report.data
        self.setWindowTitle('ROP-Insight 报告快照 · '+data['report_id'][:8])
        self.identity.setText('图像ID：'+data['source']['image']['image_id']+'\n运行ID：'+data['source']['run']['run_id'])
        for browser,detailed in zip(self.browsers,(False,True)):
            browser.setHtml(render_html(report,detailed))
        self.status.setText('PDF导出包含详细报告、精确数值JSON及来源关联。')
        self.update_busy()

    def choose_export(self):
        parent=QFileDialog.getExistingDirectory(self,'选择报告保存位置')
        if parent:self.export_to(parent)

    def export_to(self,parent):
        started=self.export_callback(self.report,parent)
        if started:self.status.setText('正在后台生成PDF报告…')
        return started

    def update_busy(self):
        self.export_button.setEnabled(not self.exporter.busy and not self._closing)

    def export_finished(self,path,error):
        self.status.setText(error if error else '报告已保存：'+str(path))
        if self._closing:self.close()

    def closeEvent(self,event):
        if self.exporter.busy:
            self._closing=True;self.update_busy();self.status.setText('正在等待报告写入安全结束…');event.ignore()
        else:super().closeEvent(event)
