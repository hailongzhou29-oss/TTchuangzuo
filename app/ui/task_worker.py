from PySide6.QtCore import QObject, QRunnable, Signal, Slot
from threading import Event


class TaskSignals(QObject):
    text = Signal(str, str)
    finished = Signal(str, object)


class TaskWorker(QRunnable):
    def __init__(self, service, snapshot, cancel, provider=None):
        super().__init__()
        self.setAutoDelete(False)
        self.completed=Event()
        self.result=None
        self.service, self.snapshot, self.cancel, self.provider = service, snapshot, cancel, provider
        self.signals = TaskSignals()

    @Slot()
    def run(self):
        task_id = self.snapshot['task_id']
        partial = []
        def receive(text):
            partial.append(text)
            self.signals.text.emit(task_id, text)
        try:
            result = self.service.execute(self.snapshot, self.cancel, receive, self.provider)
        except Exception as exc:
            result = dict(status='storage_failed', text=''.join(partial), error='任务落盘失败：' + str(exc), usage={})
        self.result=result
        self.completed.set()
        self.signals.finished.emit(task_id, result)
