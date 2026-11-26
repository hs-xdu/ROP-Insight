"""Small anonymous-case editor with explicit local save and immutable revisions."""

from PyQt6.QtCore import Qt,pyqtSignal
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,QPlainTextEdit,QLabel,QDialogButtonBox,QFileDialog
from rop_insight.models.case_metadata import EYES
from rop_insight.services.case_store import save_case_revision


class CaseDialog(QDialog):
    saved=pyqtSignal(object,object)

    def __init__(self,metadata,run_id=None,parent=None):
        super().__init__(parent)
        self.metadata,self.run_id=metadata,run_id
        self.setWindowTitle('匿名研究病例信息');self.resize(540,470)
        layout=QVBoxLayout(self)
        label=QLabel('仅保存研究编号、眼别、日期和备注。病例信息不进入模型；备注可能包含身份信息，请按需填写。')
        label.setWordWrap(True);layout.addWidget(label)
        form=QFormLayout();layout.addLayout(form)
        self.case_id=QLineEdit(metadata.case_id);self.case_id.setMaxLength(64);form.addRow('病例编号',self.case_id)
        self.eye=QComboBox()
        for key,title in EYES.items():self.eye.addItem(title,key)
        self.eye.setCurrentIndex(self.eye.findData(metadata.eye));form.addRow('眼别',self.eye)
        self.exam_date=QLineEdit(metadata.exam_date or '');self.exam_date.setPlaceholderText('可选，YYYY-MM-DD');form.addRow('检查日期',self.exam_date)
        self.notes=QPlainTextEdit(metadata.notes);self.notes.setPlaceholderText('可选，最多2000字符');form.addRow('备注',self.notes)
        self.error=QLabel();self.error.setWordWrap(True);self.error.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.error)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存并关联')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        self.buttons.accepted.connect(self.choose_save);self.buttons.rejected.connect(self.reject);layout.addWidget(self.buttons)

    def draft(self):
        return self.metadata.revised(self.case_id.text(),self.eye.currentData(),self.exam_date.text(),self.notes.toPlainText())

    def choose_save(self):
        try:self.draft()
        except (ValueError,TypeError) as exc:self.error.setText(str(exc));return
        folder=QFileDialog.getExistingDirectory(self,'选择病例资料保存位置（本地）')
        if folder:self.save_to(folder)

    def save_to(self,folder):
        try:
            metadata=self.draft();path=save_case_revision(metadata,folder,self.run_id)
        except (ValueError,TypeError,OSError) as exc:
            self.error.setText('保存失败：'+str(exc));return False
        self.saved.emit(metadata,path);self.accept();return True
