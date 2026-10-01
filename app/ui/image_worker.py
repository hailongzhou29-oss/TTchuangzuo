from PySide6.QtCore import QObject, QRunnable, Signal, Slot
from threading import Event


class ImageSignals(QObject):
    state = Signal(str, str)
    finished = Signal(str, object)


class ImageWorker(QRunnable):
    def __init__(self, service, task_id, cancel, operation='submit', snapshot=None, provider=None):
        super().__init__()
        self.setAutoDelete(False)
        self.completed=Event()
        self.result=None
        self.service, self.task_id, self.cancel = service, task_id, cancel
        self.operation, self.snapshot, self.provider = operation, snapshot, provider
        self.signals = ImageSignals()

    @Slot()
    def run(self):
        try:
            if self.operation == 'submit':
                result = self.service.execute(self.snapshot, self.cancel, lambda state: self.signals.state.emit(self.task_id, state), self.provider)
            elif self.operation == 'query':
                result = self.service.query(self.task_id, self.cancel, self.provider)
            else:
                result = self.service.materialize(self.task_id, self.cancel, lambda state: self.signals.state.emit(self.task_id, state), self.provider)
        except Exception as exc:
            result = dict(status='storage_failed', error='图片任务未完成：' + str(exc), images=[])
        self.result=result
        self.completed.set()
        self.signals.finished.emit(self.task_id, result)
