"""Export immutable snapshots off the GUI thread; wait safely on close."""

import logging
from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt
from rop_insight.services.result_exporter import export_bundle


class ExportWorker(QObject):
    done = pyqtSignal(object, str)

    def __init__(self,snapshot,parent_dir,job=None):
        super().__init__()
        self.snapshot,self.parent_dir=snapshot,parent_dir
        self.job=job

    def run(self):
        try:
            result=(self.job or export_bundle)(self.snapshot,self.parent_dir)
            self.done.emit(result,'')
        except Exception:
            logging.getLogger('rop_insight.analysis').exception('Result export failed')
            self.done.emit(None,'导出失败，请检查目录权限、磁盘空间及本地日志；本次未发布结果目录。')


class ExportController(QObject):
    changed=pyqtSignal()
    finished=pyqtSignal(object,str)

    def __init__(self,parent=None,job=None):
        super().__init__(parent)
        self._thread=self._worker=None
        self._outcome=(None,'')
        self.job=job

    @property
    def busy(self):
        return self._thread is not None

    def start(self,snapshot,parent_dir):
        if self.busy:
            return False
        thread=QThread(self)
        worker=ExportWorker(snapshot,parent_dir,self.job)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._receive)
        worker.done.connect(thread.quit,Qt.ConnectionType.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finish)
        self._thread,self._worker=thread,worker
        thread.start()
        self.changed.emit()
        return True

    def _receive(self,path,error):
        self._outcome=(path,error)

    def _finish(self):
        thread=self._thread
        self._thread=self._worker=None
        thread.deleteLater()
        self.changed.emit()
        self.finished.emit(*self._outcome)
