"""Open the exact saved text/PDF. No report builder or model calls."""
from PyQt6.QtCore import QBuffer,QByteArray,QIODevice
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtPdfWidgets import QPdfView
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QTabWidget,QPlainTextEdit


class SavedReportWindow(QDialog):
    def __init__(self,saved,parent=None):
        super().__init__(parent)
        self.setWindowTitle('已有报告 · '+saved['report_id']);self.resize(900,820)
        self._released=False
        layout=QVBoxLayout(self);tabs=QTabWidget();layout.addWidget(tabs)
        text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText(saved['text']);tabs.addTab(text,'原报告正文')
        self.view=QPdfView(self);self.pdf=QPdfDocument(self)
        self.buffer=QBuffer(self);self.buffer.setData(QByteArray(saved['pdf']));self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.pdf.load(self.buffer)
        if self.pdf.status()!=QPdfDocument.Status.Ready:
            self._release();raise ValueError('保存的PDF无法读取')
        self.view.setDocument(self.pdf);self.view.setPageMode(QPdfView.PageMode.MultiPage);self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        tabs.addTab(self.view,'原PDF')
        self.finished.connect(self._release)

    def _release(self):
        if not self._released:
            self._released=True;self.view.setDocument(None);self.pdf.close();self.buffer.close()

    def closeEvent(self,event):
        self._release();event.accept()
