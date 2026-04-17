import time

from PyQt5.QtCore import QThread, pyqtSignal, Qt, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QHBoxLayout, QVBoxLayout, QPushButton, QWidget
import numpy as np
import cv2

import os
import sys
import threading
from datetime import datetime

from camera import PySpinCamera
from core.config import AppConfigManager
from adapters.lcd_control import LCDMode, LCDController


class VideoThread(QThread):
    change_pixmap_signal = pyqtSignal(QImage)
    error_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._run_flag = True
        self.camera = PySpinCamera(0)
        self.camera.open()
        self._exit_ready_flag = threading.Event()
        self.save_flag = False
        self.reload_flag = False

    def run(self):
        if self.camera.cam is None:
            self._exit_ready_flag.set()
            self.error_signal.emit("Camera cannot be found")
            return

        while self._run_flag:
            img = self.camera.get_image_data()

            if self.save_flag:
                self.save_flag = False
                self._save_image(img)

            if self.reload_flag:
                self.reload_flag = False
                self.camera.configure()

            if img is not None:
                h, w = img.shape
                bytes_per_line = int(w if img.dtype == np.uint8 else 2*w)
                convert_to_Qt_format = QImage(
                    img.data, w, h, bytes_per_line,
                    QImage.Format_Grayscale8 if img.dtype == np.uint8 else QImage.Format_Grayscale16)
                p = convert_to_Qt_format.scaled(1000, 680, Qt.KeepAspectRatio, )
                self.change_pixmap_signal.emit(p)
        self._exit_ready_flag.set()

    @pyqtSlot()
    def trigger_save(self):
        self.save_flag = True

    @pyqtSlot()
    def trigger_reload(self):
        self.reload_flag = True

    def _save_image(self, image):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = os.path.join(
            AppConfigManager.config.camera.image_save_dir, f"image_{timestamp}.png")
        cv2.imwrite(image_path, image)
        # cv2.imwrite(image_path, image, [cv2.IMWRITE_PNG_COMPRESSION, 0])

    def stop(self):
        """Sets run flag to False and waits for thread to finish"""
        self._run_flag = False
        self._exit_ready_flag.wait()
        self.camera.close()
        self.wait()

class LCDControlThread(QThread):
    def __init__(self):
        super().__init__()
        self._reverse = False
        self._lcd_controller = LCDController()
        self._update_pending = False
        self._lcd_mode = LCDMode.CIRCULAR
        self._run_flag = True
        self._exit_ready_flag = threading.Event()

    @pyqtSlot()    
    def trigger_reverse(self):
        self._reverse = not self._reverse
        self._update_pending = True

    @pyqtSlot()
    def trigger_split_x(self):
        self._lcd_mode = LCDMode.SPLIT_IN_X
        self._update_pending = True

    @pyqtSlot()
    def trigger_split_y(self):
        self._lcd_mode = LCDMode.SPLIT_IN_Y
        self._update_pending = True

    @pyqtSlot()
    def trigger_circular(self):
        self._lcd_mode = LCDMode.CIRCULAR
        self._update_pending = True

    @pyqtSlot()
    def trigger_update_pos(self, change_x, change_y):
        self._lcd_controller.update_center(change_x, change_y)
        self._update_pending = True

    def run(self):
        while self._run_flag:
            if self._update_pending:
                self._update_pending = False
                self._lcd_controller.update(self._lcd_mode, 0, 50, self._reverse)
            time.sleep(0.3)
        self._exit_ready_flag.set()

    def stop(self):
        """Sets run flag to False and waits for thread to finish"""
        self._run_flag = False
        self._exit_ready_flag.wait()
        self._lcd_controller.close()
        self.wait()

class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stream")
        self.label = QLabel(self)
        self.capture_btn = QPushButton("Capture")
        self.config_btn = QPushButton("Reload configuration")
        
        self.split_x_btn = QPushButton("-")
        self.split_y_btn = QPushButton("|")
        self.circular_btn = QPushButton("O")
        self.reverse_btn = QPushButton("*")
        
        self.label.resize(640, 480)

        # Create thread
        self.video_thread = VideoThread()
        self.video_thread.change_pixmap_signal.connect(self.update_image)
        self.video_thread.error_signal.connect(self.close)
        self.video_thread.start()

        self.lcd_thread = LCDControlThread()
        self.lcd_thread.start()

        layout = QHBoxLayout()
        menu_layout = QVBoxLayout()
        layout.addWidget(self.label)
        menu_layout.setSpacing(10)
        menu_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(menu_layout)
        
        menu_layout.addStretch(1)
        menu_layout.addWidget(self.capture_btn)
        menu_layout.addWidget(self.config_btn)
        menu_layout.addStretch(1)

        pattern_layout = QHBoxLayout()
        pattern_layout.addWidget(self.split_x_btn)
        pattern_layout.addWidget(self.split_y_btn)
        pattern_layout.addWidget(self.circular_btn)
        pattern_layout.addWidget(self.reverse_btn)
        menu_layout.addLayout(pattern_layout)
        
        self.setLayout(layout)

        self.capture_btn.clicked.connect(self.video_thread.trigger_save)
        self.config_btn.clicked.connect(self.video_thread.trigger_reload)
        self.split_x_btn.clicked.connect(self.lcd_thread.trigger_split_x)
        self.split_y_btn.clicked.connect(self.lcd_thread.trigger_split_y)
        self.circular_btn.clicked.connect(self.lcd_thread.trigger_circular)
        self.reverse_btn.clicked.connect(self.lcd_thread.trigger_reverse)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_X:
            self.lcd_thread.trigger_split_x()
        elif event.key() == Qt.Key_Y:
            self.lcd_thread.trigger_split_y()
        elif event.key() == Qt.Key_C:
            self.lcd_thread.trigger_circular()
        elif event.key() == Qt.Key_R:
            self.lcd_thread.trigger_reverse()
        elif event.key() == Qt.Key_W:
            self.lcd_thread.trigger_update_pos(1, 0)
        elif event.key() == Qt.Key_S:
            self.lcd_thread.trigger_update_pos(-1, 0)
        elif event.key() == Qt.Key_A:
            self.lcd_thread.trigger_update_pos(0, -1)
        elif event.key() == Qt.Key_D:
            self.lcd_thread.trigger_update_pos(0, 1)
        else:
            pass

    def update_image(self, qt_img):
        """Updates the image_label with a new image"""
        self.label.setPixmap(QPixmap.fromImage(qt_img))

    def closeEvent(self, event):
        self.video_thread.stop()
        self.lcd_thread.stop()
        # we tell the OS it's okay to hide the window.
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    a = App()
    a.show()
    sys.exit(app.exec_())
