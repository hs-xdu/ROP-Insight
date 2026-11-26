"""Minimal case creation/selection, with SQLite work off the GUI thread."""
from PyQt6.QtCore import Qt,QDate,pyqtSignal
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QPushButton,QLabel,QComboBox,QLineEdit,QFileDialog,QDialogButtonBox)
from rop_insight.services.export_controller import ExportController
from rop_insight.services.local_records import record_job


class CaseSelector(QDialog):
    selected=pyqtSignal(str,object)

    def __init__(self,root=None,current_case=None,parent=None):
        super().__init__(parent)
        self.root=None;self.current_case=current_case;self._closing=False
        self.setWindowTitle('病例与本地资料库');self.resize(570,400)
        self.worker=ExportController(self,job=record_job);self.worker.finished.connect(self._finished);self.worker.changed.connect(self._controls)
        layout=QVBoxLayout(self)
        self.folder=QPushButton('选择资料库文件夹');self.folder.clicked.connect(self.choose_root);layout.addWidget(self.folder)
        self.location=QLabel('请选择专用资料文件夹；不使用原五表资料库。');self.location.setWordWrap(True);self.location.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.location)
        self.existing=QComboBox();layout.addWidget(self.existing)
        form=QFormLayout();layout.addLayout(form)
        self.code=QLineEdit();form.addRow('新病例编号（匿名）',self.code)
        self.eye=QComboBox()
        for label,value in (('未指定','unspecified'),('左眼','left'),('右眼','right')):self.eye.addItem(label,value)
        form.addRow('左右眼',self.eye)
        self.date=QLineEdit(QDate.currentDate().toString('yyyy-MM-dd'));self.date.setPlaceholderText('可清空；YYYY-MM-DD');form.addRow('检查日期',self.date)
        self.create=QPushButton('创建病例');self.create.clicked.connect(self.create_case);layout.addWidget(self.create)
        self.temporary=QPushButton('不关联病例，使用临时分析');self.temporary.clicked.connect(self.use_temporary);layout.addWidget(self.temporary)
        self.status=QLabel();self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.status)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('使用选中病例');self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        self.buttons.accepted.connect(self.apply);self.buttons.rejected.connect(self.reject);layout.addWidget(self.buttons)
        self._controls()
        if root:self.load_root(root)

    def choose_root(self):
        root=QFileDialog.getExistingDirectory(self,'选择精简版本地资料库目录')
        if root:self.load_root(root)

    def load_root(self,root):
        if self.worker.busy:return False
        self.status.setText('正在后台读取资料库…')
        return self.worker.start(dict(kind='cases',root=str(root)),None)

    def create_case(self):
        if not self.root or self.worker.busy:return False
        return self.worker.start(dict(kind='create',root=self.root,code=self.code.text(),eye=self.eye.currentData(),date=self.date.text().strip()),None)

    def _controls(self):
        busy=self.worker.busy
        self.temporary.setEnabled(not busy)
        self.folder.setEnabled(not busy);self.create.setEnabled(bool(self.root) and not busy)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.existing.count()) and not busy)

    def _finished(self,result,error):
        if error or not result['ok']:self.status.setText(error or result['message'])
        else:
            self.root=result['root'];self.location.setText(self.root);self.existing.clear()
            selected_id=(result.get('case') or self.current_case or {}).get('case_id')
            for case in result['cases']:
                eye={'left':'左眼','right':'右眼','unspecified':'未指定'}[case['eye']]
                self.existing.addItem(f"{case['case_code']} · {eye} · {case['exam_date'] or '日期未填写'}",case)
                if case['case_id']==selected_id:self.existing.setCurrentIndex(self.existing.count()-1)
            self.status.setText('病例已创建，请点击“使用选中病例”' if result['kind']=='create' else '请选择已有病例或创建新病例')
        self._controls()
        if self._closing:self.close()

    def use_temporary(self):
        if not self.worker.busy:self.selected.emit(self.root or '',None);self.accept()

    def apply(self):
        if self.root and not self.worker.busy and self.existing.currentData():
            self.selected.emit(self.root,self.existing.currentData());self.accept()

    def closeEvent(self,event):
        if self.worker.busy:self._closing=True;event.ignore()
        else:event.accept()

    def reject(self):
        if self.worker.busy:self._closing=True
        else:super().reject()
