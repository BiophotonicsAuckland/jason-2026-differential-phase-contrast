from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
import numpy as np

import sys
import threading

from src.camera import PySpinCamera


class VideoThread(QThread):
    change_pixmap_signal = pyqtSignal(QImage)
    error_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._run_flag = True
        self.camera = PySpinCamera(0)
        self.camera.open()
        self._exit_ready_flag = threading.Event()

    def run(self):
        if self.camera.cam is None:
            self._exit_ready_flag.set()
            self.error_signal.emit("Camera cannot be found")
            return

        while self._run_flag:
            img = self.camera.get_image_data()
            if img is not None:
                h, w = img.shape
                bytes_per_line = int(w if img.dtype == np.uint8 else 2*w)
                convert_to_Qt_format = QImage(
                    img.data, w, h, bytes_per_line,
                    QImage.Format_Grayscale8 if img.dtype == np.uint8 else QImage.Format_Grayscale16)
                p = convert_to_Qt_format.scaled(800, 800, Qt.KeepAspectRatio)
                self.change_pixmap_signal.emit(p)
        self._exit_ready_flag.set()

    def stop(self):
        """Sets run flag to False and waits for thread to finish"""
        self._run_flag = False
        self._exit_ready_flag.wait()
        self.camera.close()
        self.wait()


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Non-Blocking Stream")
        self.label = QLabel(self)
        self.label.resize(640, 480)

        # Create thread
        self.thread = VideoThread()
        self.thread.change_pixmap_signal.connect(self.update_image)
        self.thread.error_signal.connect(self.close)
        self.thread.start()

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

    def update_image(self, qt_img):
        """Updates the image_label with a new image"""
        self.label.setPixmap(QPixmap.fromImage(qt_img))

    def closeEvent(self, event):
        self.thread.stop()
        # we tell the OS it's okay to hide the window.
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    a = App()
    a.show()
    sys.exit(app.exec_())
