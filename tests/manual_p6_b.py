"""Independent P6-B acceptance window; synthetic data only, no model execution."""
import sys
from pathlib import Path
from threading import Event
from uuid import uuid4
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage,QPainter,QColor
from PyQt6.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QLabel,QPushButton
from rop_insight.models.managed_data import CaseRequest,StoreError
from rop_insight.models.managed_image import ImageImportRequest
from rop_insight.models.analysis_result import timestamp
from rop_insight.services.database import initialize_new_store
from rop_insight.services.data_repository import CaseRepository
from rop_insight.services.image_loader import ImageLoader
from rop_insight.services.managed_store import ManagedImageStore
from rop_insight.services.image_import_controller import ImageImportController
from rop_insight.services.export_controller import ExportController
from rop_insight.ui.image_view import ImageView


class AcceptanceWindow(QMainWindow):
    def __init__(self,parent_folder=None):
        super().__init__()
        root=Path(parent_folder) if parent_folder else Path(__file__).resolve().parents[1]/'.runtime'/'p6-b-demo'
        self.root=(root/uuid4().hex).absolute();self.root.mkdir(parents=True)
        self.setWindowTitle('P6-B 原图托管工程验收 · 合成图像 · 无模型推理');self.resize(1000,780)
        source=self.root/'source';source.mkdir()
        image=QImage(600,400,QImage.Format.Format_RGB32);image.fill(QColor('#173047'))
        painter=QPainter(image);painter.setBrush(QColor('#db8648'));painter.setPen(Qt.PenStyle.NoPen);painter.drawEllipse(130,30,340,340);painter.end()
        path=source/'合成图像.png';image.save(str(path),'PNG')
        ridge=QImage(600,400,QImage.Format.Format_Grayscale8);ridge.fill(0)
        painter=QPainter(ridge);painter.fillRect(270,160,60,80,QColor('white'));painter.end()
        ridge_path=source/'合成Ridge.png';ridge.save(str(ridge_path),'PNG')
        self.store=initialize_new_store(self.root/'data');self.service=ManagedImageStore(self.store)
        case=CaseRepository(self.store).create_case(CaseRequest(str(uuid4()),str(uuid4()),'DEMO-P6-B',timestamp()))
        document=ImageLoader().load(path)
        self.request=ImageImportRequest.capture(document,case.case_id,case.revision.revision_id,'left','2026-11-26',ridge_path)
        self.importer=ImageImportController(self.service,self)
        self.importer.finished.connect(self._imported)
        self.read_cancel=Event();self.reader=ExportController(self,job=self._read,error_message='打开受阻')
        self.reader.finished.connect(self._read_finished)
        self._closing=False
        content=QWidget();self.setCentralWidget(content);layout=QVBoxLayout(content)
        self.info=QLabel('P6-B 独立验收：病例 DEMO-P6-B · 左眼。此窗口只使用自动生成的合成图像。');self.info.setWordWrap(True);layout.addWidget(self.info)
        self.view=ImageView();self.view.setBackgroundBrush(QColor('#173047'));self.view.set_image(document.image);layout.addWidget(self.view,1)
        self.import_button=QPushButton('1. 托管原图和输入 Ridge');self.import_button.clicked.connect(self.start_import);layout.addWidget(self.import_button)
        self.move_button=QPushButton('2. 移走源文件，从仓库重新打开');self.move_button.clicked.connect(self.move_and_open);self.move_button.setEnabled(False);layout.addWidget(self.move_button)
        self.corrupt_button=QPushButton('3. 损坏演示副本，验证阻止打开');self.corrupt_button.clicked.connect(self.corrupt_and_check);self.corrupt_button.setEnabled(False);layout.addWidget(self.corrupt_button)
        self.location=QLabel('演示数据目录：'+str(self.root));self.location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);self.location.setWordWrap(True);layout.addWidget(self.location)

    def start_import(self):
        self.import_button.setEnabled(False);self.info.setText('正在后台托管并校验原图及 Ridge…')
        self.importer.start_request(self.request)

    def _imported(self,record,error):
        self.info.setText(error or '托管完成：ready / valid。原图、Ridge 原文件和规范二值副本均已校验。')
        self.move_button.setEnabled(not error and not self._closing)
        self.import_button.setEnabled(bool(error) and not self._closing)
        if self._closing:self.close()

    def _read(self,image_id,cancel):
        try:
            document=self.service.open_image(image_id,cancel)
            ridge=self.service.open_ridge(image_id,cancel)
            return document,ridge
        except StoreError as error:raise ValueError(error.code+'：'+str(error)) from error

    def move_and_open(self):
        for path in (self.request.source,self.request.ridge.source):
            if path.exists():
                if path.resolve().parent!=self.root/'source':raise ValueError('演示源路径不符')
                path.rename(path.with_suffix('.moved'))
        self.view.clear_image();self.move_button.setEnabled(False);self.read_cancel=Event()
        self.info.setText('源文件已移走，正在后台从仓库重新打开…')
        self.reader.start(self.request.image_id,self.read_cancel)

    def corrupt_and_check(self):
        record=self.service.get_image(self.request.image_id)
        target=(self.store.root/record.managed_relpath).resolve()
        if not target.is_relative_to(self.root):raise ValueError('演示副本路径越界')
        target.write_bytes(b'synthetic demo corruption')
        self.view.clear_image();self.corrupt_button.setEnabled(False);self.read_cancel=Event()
        self.reader.start(self.request.image_id,self.read_cancel)

    def _read_finished(self,result,error):
        if error:self.info.setText('检查结果：'+error+'；损坏副本未打开。')
        else:
            document,ridge=result;self.view.set_image(document.image)
            if ridge:
                self.view.set_mask(ridge.masks[0]);self.view.display_mode='overlay';self.view.update_layers()
            self.info.setText('验收通过：源文件已移走，仍可从托管副本显示图像，并恢复已保存的 Ridge 输入。')
            self.corrupt_button.setEnabled(not self._closing)
        if self._closing:self.close()

    def closeEvent(self,event):
        if self.importer.busy or self.reader.busy:
            self._closing=True;self.importer.cancel();self.read_cancel.set();event.ignore()
        else:event.accept()


if __name__=='__main__':
    import logging
    app=QApplication(sys.argv)
    window=AcceptanceWindow()
    logging.basicConfig(filename=str(window.root/'acceptance.log'),encoding='utf-8',level=logging.INFO)
    window.show()
    sys.exit(app.exec())
