"""Background export of an immutable prepared field display."""

from PyQt6.QtCore import QThread, pyqtSignal

from core.animation_video import export_animation_video


class VideoExportWorker(QThread):
    progress = pyqtSignal(int, str)
    exported = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, parent=None, **inputs):
        super().__init__(parent)
        self.inputs = inputs

    def run(self):
        try:
            path = export_animation_video(
                **self.inputs, progress=self.progress.emit,
                cancelled=self.isInterruptionRequested)
            self.exported.emit(path)
        except Exception as error:
            self.failed.emit(str(error))
