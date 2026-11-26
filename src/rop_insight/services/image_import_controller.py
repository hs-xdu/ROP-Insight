"""Reuse the established QThread lifecycle for P6-B import and cancellation."""
from threading import Event
from rop_insight.models.managed_data import StoreError
from rop_insight.services.export_controller import ExportController


class ImageImportController(ExportController):
    def __init__(self,service,parent=None):
        self.service=service
        self.cancel_event=Event()
        super().__init__(parent,job=self._import,error_message='图像托管失败')

    def _import(self,request,cancel):
        try:return self.service.import_image(request,cancel)
        except StoreError as error:raise ValueError(error.code+'：'+str(error)) from error

    def start_request(self,request):
        if self.busy:return False
        self.cancel_event=Event()
        return super().start(request,self.cancel_event)

    def cancel(self):self.cancel_event.set()
