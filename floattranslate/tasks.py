from PySide6.QtCore import QObject, QRunnable, Signal


class Signals(QObject):
    finished = Signal(object)
    progress = Signal(object)


class Task(QRunnable):
    def __init__(self, identity, function):
        super().__init__()
        self.identity = identity
        self.function = function
        self.signals = Signals()

    def run(self):
        try:
            result = self.function()
            self.signals.finished.emit((self.identity, result, None))
        except Exception as exc:
            self.signals.finished.emit((self.identity, None, str(exc)))
