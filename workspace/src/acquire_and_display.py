from queue import Queue
import queue
import time

from PyQt5.QtCore import QThread, pyqtSignal, Qt, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QHBoxLayout, QVBoxLayout, QPushButton, QWidget
import numpy as np
import cv2
from pathlib import Path

import os
import sys
import threading
from datetime import datetime

from camera import PySpinCamera
from core.config import AppConfigManager
from adapters.lcd_control import LCDMode, LCDController
from optics import differential_phase_contrast, fdspi, standardize


class VideoThread(QThread):
    change_pixmap_signal = pyqtSignal(QImage)
    error_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._run_flag = True
        self.camera = PySpinCamera(0)
        self.camera.open()
        self._exit_ready_flag = threading.Event()
        self._task_queue = Queue()
    
    @pyqtSlot()
    def trigger(self, function, blocking=False):
        finished = threading.Event()
        def f(*args, **kwargs):
            function(*args, **kwargs)
            finished.set()
        self._task_queue.put(f)
        if blocking:
            finished.wait()

    @pyqtSlot()
    def trigger_pseudo_block(self, function):
        finished = threading.Event()
        def f(*args, **kwargs):
            finished.set()
            function(*args, **kwargs)
        self._task_queue.put(f)
        finished.wait()

    def run(self):
        if self.camera.cam is None:
            self._exit_ready_flag.set()
            self.error_signal.emit("Camera cannot be found")
            return

        while self._run_flag:
            task = None
            ## Fetch task first to make sure the image is never captured before the task
            try:
                task = self._task_queue.get(timeout=0.1)
            except queue.Empty:
                pass
            
            img = self.camera.get_image_data()

            if task is not None:
                task(img)
                # threading.Thread(target=lambda: task(img)).start()

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
    def trigger_save(self, image_dir=None, image_name=None, blocking=False):
        self.trigger_pseudo_block(lambda im: self._save_image(im, image_name=image_name, image_dir=image_dir))

    @pyqtSlot()
    def trigger_put_queue(self, im_queue, blocking=False):
        self.trigger_pseudo_block(lambda im: im_queue.put(im))
    
    @pyqtSlot()
    def trigger_measure_brightness(self, result_queue):
        self.trigger(lambda im: result_queue.put((im/65335).sum()), True)

    @pyqtSlot()
    def trigger_reload(self):
        self._task_queue.put(lambda *args: self.camera.configure())

    def _save_image(self, image, image_name=None, image_dir=None):
        if image_name is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            image_name = f"image_{timestamp}"

        if image_dir is None:
            image_dir = '.'
        
        image_path = Path(AppConfigManager.config.camera.image_save_dir)/image_dir
        os.makedirs(image_path, exist_ok=True)
        cv2.imwrite(image_path/f"{image_name}.png", image)
        cv2.imwrite(image_path, image, [cv2.IMWRITE_PNG_COMPRESSION, 0])

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
        self._update_queue = Queue()
        self.update_callback = lambda: self._lcd_controller.update(self._lcd_mode, 0, 20, self._reverse)

    @pyqtSlot()
    def trigger(self, function, blocking=False):
        finished = threading.Event()
        def f():
            function()
            finished.set()
        self._update_queue.put(f)
        if blocking:
            finished.wait()

    @pyqtSlot()
    def trigger_reverse(self, blocking=False):
        def f():
            self._reverse = not self._reverse
            self.update_callback()
        self.trigger(f, blocking)
        

    @pyqtSlot()
    def trigger_split_x(self, blocking=False):
        def f():
            self._lcd_mode = LCDMode.SPLIT_IN_X
            self.update_callback()
        self.trigger(f, blocking)

    @pyqtSlot()
    def trigger_split_y(self, blocking=False):
        def f():
            self._lcd_mode = LCDMode.SPLIT_IN_Y
            self.update_callback()
        self.trigger(f, blocking)

    @pyqtSlot()
    def trigger_circular(self, blocking=False):
        def f():
            self._lcd_mode = LCDMode.CIRCULAR
            self.update_callback()
        self.trigger(f, blocking)

    @pyqtSlot()
    def trigger_update_pos(self, change_x, change_y):
        def f():
            self._lcd_controller.update_center(change_x, change_y)
            self.update_callback()
        self.trigger(f, True)
    
    def run(self):
        while self._run_flag:
            try:
                task = self._update_queue.get(timeout=2)
                task()
            except queue.Empty:
                continue
        self._exit_ready_flag.set()

    def stop(self):
        """Sets run flag to False and waits for thread to finish"""
        self._run_flag = False
        self._exit_ready_flag.wait()
        self._lcd_controller.close()
        self.wait()

class CaptureThread(QThread):
    def __init__(self, video_thread: VideoThread, lcd_thread: LCDControlThread):
        super().__init__()
        self.video_thread = video_thread
        self.lcd_thread = lcd_thread

    def run(self):
        im_queue = queue.Queue()
        start_time = time.time()*1000
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.lcd_thread.trigger_split_x(True)
        print(time.time()*1000-start_time)
        self.video_thread.trigger_put_queue(im_queue)
        print(time.time()*1000-start_time)
        self.lcd_thread.trigger_reverse(True)
        print(time.time()*1000-start_time)
        self.video_thread.trigger_put_queue(im_queue)
        print(time.time()*1000-start_time)
        self.lcd_thread.trigger_split_y(True)
        self.video_thread.trigger_put_queue(im_queue)
        self.lcd_thread.trigger_reverse(True)
        self.video_thread.trigger_put_queue(im_queue)
        print(time.time()*1000-start_time)
        working_dir = AppConfigManager.config.camera.image_save_dir/timestamp
        os.makedirs(working_dir, exist_ok=True)

        bottom_im = im_queue.get()
        top_im = im_queue.get()
        right_im = im_queue.get()
        left_im = im_queue.get()

        cv2.imwrite(working_dir/"brightfield_tb.tiff", standardize(bottom_im*1.+top_im), [cv2.IMWRITE_TIFF_COMPRESSION, 1])
        cv2.imwrite(working_dir/"brightfield_lr.tiff", standardize(left_im*1.+right_im), [cv2.IMWRITE_TIFF_COMPRESSION, 1])
        
        cv2.imwrite(working_dir/'01_top.tiff', top_im, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
        cv2.imwrite(working_dir/'02_bottom.tiff', bottom_im, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
        cv2.imwrite(working_dir/'04_left.tiff', left_im, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
        cv2.imwrite(working_dir/'03_right.tiff', right_im, [cv2.IMWRITE_TIFF_COMPRESSION, 1])

        # vertical_res = differential_phase_contrast(top_im, bottom_im)
        # cv2.imwrite(working_dir/"vertical.png", standardize(vertical_res))
        # horizontal_res = differential_phase_contrast(right_im, left_im)
        # cv2.imwrite(working_dir/"horizontal.png", standardize(horizontal_res))
        
        # res = fdspi(vertical_res, -horizontal_res)
        # cv2.imwrite(working_dir/"phase_diagram.png", standardize(res))
        # cv2.imwrite(working_dir/"corrected_phase_diagram.png", standardize(res - np.load(working_dir/'..'/"background"/"phase.npy")))

class AdjustThread(QThread):
    def __init__(self, video_thread: VideoThread, lcd_thread: LCDControlThread):
        super().__init__()
        self.video_thread = video_thread
        self.lcd_thread = lcd_thread

    def _measure_delta_brightness(self):
        result_queue = Queue(1)
        delta_brightness = 0
        
        self.video_thread.trigger_measure_brightness(result_queue)
        delta_brightness = result_queue.get()
        self.lcd_thread.trigger_reverse(True)
        self.video_thread.trigger_measure_brightness(result_queue)
        delta_brightness -= result_queue.get()
        self.lcd_thread.trigger_reverse(True)

        return delta_brightness
    
    def run(self):
        self.lcd_thread.trigger_split_x(True)
        delta_brightness = self._measure_delta_brightness()

        while delta_brightness > 0:
            self.lcd_thread.trigger_update_pos(1,0)
            delta_brightness = self._measure_delta_brightness()
            print(f"Brightness: {delta_brightness}")

        while delta_brightness < 0:
            self.lcd_thread.trigger_update_pos(-1,0)
            delta_brightness = self._measure_delta_brightness()
            print(f"Brightness: {delta_brightness}")

        self.lcd_thread.trigger_update_pos(1,0)
        delta_brightness2 = self._measure_delta_brightness()
        print(f"Brightness: {delta_brightness2}")

        if abs(delta_brightness2) > abs(delta_brightness):
            self.lcd_thread.trigger_update_pos(-1,0)

        self.lcd_thread.trigger_split_y(True)
        delta_brightness = self._measure_delta_brightness()

        while delta_brightness > 0:
            self.lcd_thread.trigger_update_pos(0,1)
            delta_brightness = self._measure_delta_brightness()
            print(f"Brightness: {delta_brightness}")

        while delta_brightness < 0:
            self.lcd_thread.trigger_update_pos(0,-1)
            delta_brightness = self._measure_delta_brightness()
            print(f"Brightness: {delta_brightness}")

        self.lcd_thread.trigger_update_pos(0,1)
        delta_brightness2 = self._measure_delta_brightness()
        print(f"Brightness: {delta_brightness2}")

        if abs(delta_brightness2) > abs(delta_brightness):
            self.lcd_thread.trigger_update_pos(0,-1)


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

        self.thread = None

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
        elif event.key() == Qt.Key_O:
            self.thread = CaptureThread(self.video_thread, self.lcd_thread)
            self.thread.start()
        elif event.key() == Qt.Key_Z:
            self.thread = AdjustThread(self.video_thread, self.lcd_thread)
            self.thread.start()
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
