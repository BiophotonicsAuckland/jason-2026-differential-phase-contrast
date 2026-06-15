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
    error_signal = pyqtSignal(str)

    def __init__(self, batch_size=1):
        super().__init__()
        self._run_flag = True
        self.camera = PySpinCamera(0)
        self.camera.open()

        self._batch_size = batch_size
        self._exit_ready_flag = threading.Event()
        self.img_queue = Queue()
        self._img_batch = []
        self._next_frame_id = 0
        self._batch_start_frame_id = 0

    def run(self):
        if self.camera.cam is None:
            self._exit_ready_flag.set()
            self.error_signal.emit("Camera cannot be found")
            return

        while self._run_flag:
            img, frame_id = self.camera.get_image_data()
            if img is not None:
                if frame_id == self._next_frame_id:
                    print(frame_id)
                    self._img_batch.append(img)
                    if len(self._img_batch) >= self._batch_size:
                        self.img_queue.put(self._img_batch)
                        self._img_batch = []
                    self._next_frame_id += 1
                elif frame_id > self._next_frame_id:
                    self._img_batch = []
                    self._next_frame_id = frame_id+(self._batch_start_frame_id %
                                                    self._batch_size-frame_id % self._batch_size) % self._batch_size
                    if self._next_frame_id == frame_id:
                        self._img_batch.append(img)
                        self._next_frame_id += 1
        self._exit_ready_flag.set()

    def set_image_batch_size(self, batch_size):
        self._batch_size = batch_size
        self._batch_start_frame_id = self._next_frame_id

    def get_image_queue(self):
        return self.img_queue

    def stop(self):
        """Sets run flag to False and waits for thread to finish"""
        self._run_flag = False
        self._exit_ready_flag.wait()
        self.camera.close()
        self.wait()

    @pyqtSlot()
    def trigger_save(self, image_dir=None, image_name=None, blocking=False):
        self.trigger_pseudo_block(lambda im: self._save_image(im, image_name=image_name, image_dir=image_dir))

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


class ImageHandlerThread(QThread):
    change_pixmap_signal = pyqtSignal(QImage)

    def __init__(self, image_queue: Queue[np.ndarray]):
        super().__init__()
        self._run_flag = True
        self.image_queue = image_queue
        self.process_fun = lambda imgs: imgs[0]

    def run(self):
        while self._run_flag:
            try:
                imgs = self.image_queue.get(timeout=1)
            except queue.Empty:
                continue

            img = self.process_fun(imgs)
            h, w = img.shape
            bytes_per_line = int(w if img.dtype == np.uint8 else 2*w)
            convert_to_Qt_format = QImage(
                img.data, w, h, bytes_per_line,
                QImage.Format_Grayscale8 if img.dtype == np.uint8 else QImage.Format_Grayscale16)
            p = convert_to_Qt_format.scaled(1000, 680, Qt.KeepAspectRatio, )
            self.change_pixmap_signal.emit(p)

    def trigger_display_processing(self, mode: int):
        if mode <= 4:
            self.process_fun = lambda imgs: imgs[mode-1]
        elif mode == 5:
            self.process_fun = lambda imgs: standardize(differential_phase_contrast(imgs[0], imgs[1]))
        elif mode == 6:
            self.process_fun = lambda imgs: standardize(differential_phase_contrast(imgs[2], imgs[3]))

    @pyqtSlot()
    def trigger_measure_brightness(self, result_queue):
        def measure_brightness_process_fun(ims):
            result_queue.put((ims[0]/65335).sum())
            return ims[0]

        time.sleep(0.4)
        self.process_fun = measure_brightness_process_fun


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
        self._frame_count = -1
        self.update_callback = lambda: self._lcd_controller.update(
            self._lcd_mode, 0, 20, self._reverse, self._frame_count)

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
    def trigger_reverse(self, frame_count: int, blocking=False):
        if self._lcd_mode == LCDMode.DPC_PATTERN or self._lcd_mode == LCDMode.CIRCULAR or self._lcd_mode == LCDMode.NONE:
            return

        def f():
            self._reverse = not self._reverse
            self._frame_count = frame_count
            self.update_callback()
        self.trigger(f, blocking)

    @pyqtSlot()
    def trigger_none(self, blocking=False):
        def f():
            self._lcd_mode = LCDMode.NONE
            self._frame_count = 0
            self.update_callback()
        self.trigger(f, blocking)

    @pyqtSlot()
    def trigger_split_x(self, frame_count: int, blocking=False):
        def f():
            self._lcd_mode = LCDMode.SPLIT_IN_X
            self._frame_count = frame_count
            self.update_callback()
        self.trigger(f, blocking)

    @pyqtSlot()
    def trigger_split_y(self, frame_count: int, blocking=False):
        def f():
            self._lcd_mode = LCDMode.SPLIT_IN_Y
            self._frame_count = frame_count
            self.update_callback()
        self.trigger(f, blocking)

    @pyqtSlot()
    def trigger_circular(self, frame_count: int, blocking=False):
        def f():
            self._lcd_mode = LCDMode.CIRCULAR
            self._frame_count = frame_count
            self.update_callback()
        self.trigger(f, blocking)

    @pyqtSlot()
    def trigger_dpc_pattern(self, blocking=False):
        def f():
            self._lcd_mode = LCDMode.DPC_PATTERN
            self._frame_count = -1
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
        start_time = time.time()*1000
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.lcd_thread.trigger_dpc_pattern(True)
        print(time.time()*1000-start_time)
        # working_dir = AppConfigManager.config.camera.image_save_dir/timestamp
        # os.makedirs(working_dir, exist_ok=True)

        # bottom_im = im_queue.get()
        # top_im = im_queue.get()
        # right_im = im_queue.get()
        # left_im = im_queue.get()

        # cv2.imwrite(working_dir/"brightfield_tb.tiff", standardize(bottom_im*1.+top_im), [cv2.IMWRITE_TIFF_COMPRESSION, 1])
        # cv2.imwrite(working_dir/"brightfield_lr.tiff", standardize(left_im*1.+right_im), [cv2.IMWRITE_TIFF_COMPRESSION, 1])

        # cv2.imwrite(working_dir/'01_top.tiff', top_im, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
        # cv2.imwrite(working_dir/'02_bottom.tiff', bottom_im, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
        # cv2.imwrite(working_dir/'04_left.tiff', left_im, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
        # cv2.imwrite(working_dir/'03_right.tiff', right_im, [cv2.IMWRITE_TIFF_COMPRESSION, 1])

        # vertical_res = differential_phase_contrast(top_im, bottom_im)
        # cv2.imwrite(working_dir/"vertical.png", standardize(vertical_res))
        # horizontal_res = differential_phase_contrast(right_im, left_im)
        # cv2.imwrite(working_dir/"horizontal.png", standardize(horizontal_res))

        # res = fdspi(vertical_res, -horizontal_res)
        # cv2.imwrite(working_dir/"phase_diagram.png", standardize(res))
        # cv2.imwrite(working_dir/"corrected_phase_diagram.png", standardize(res - np.load(working_dir/'..'/"background"/"phase.npy")))


class AdjustThread(QThread):
    def __init__(self, video_thread: VideoThread, img_handler_thread: ImageHandlerThread, lcd_thread: LCDControlThread):
        super().__init__()
        self.video_thread = video_thread
        self.img_handler_thread = img_handler_thread
        self.lcd_thread = lcd_thread

    def _measure_delta_brightness(self):
        result_queue = Queue(1)
        delta_brightness = 0

        self.img_handler_thread.trigger_measure_brightness(result_queue)
        self.lcd_thread.trigger_reverse(1, True)
        delta_brightness = result_queue.get()
        self.img_handler_thread.trigger_measure_brightness(result_queue)
        self.lcd_thread.trigger_reverse(1, True)
        delta_brightness -= result_queue.get()

        return delta_brightness

    def run(self):
        self.lcd_thread.trigger_split_x(0, True)
        self.video_thread.set_image_batch_size(1)
        while not self.video_thread.get_image_queue().empty():
            time.sleep(0.01)

        delta_brightness = self._measure_delta_brightness()

        while delta_brightness < 0:
            self.lcd_thread.trigger_update_pos(1, 0)
            delta_brightness = self._measure_delta_brightness()
            print(f"Brightness: {delta_brightness}")

        while delta_brightness > 0:
            self.lcd_thread.trigger_update_pos(-1, 0)
            delta_brightness = self._measure_delta_brightness()
            print(f"Brightness: {delta_brightness}")

        self.lcd_thread.trigger_update_pos(1, 0)
        delta_brightness2 = self._measure_delta_brightness()
        print(f"Brightness: {delta_brightness2}")

        if abs(delta_brightness2) > abs(delta_brightness):
            self.lcd_thread.trigger_update_pos(-1, 0)

        self.lcd_thread.trigger_split_y(0, True)
        delta_brightness = self._measure_delta_brightness()

        while delta_brightness < 0:
            self.lcd_thread.trigger_update_pos(0, 1)
            delta_brightness = self._measure_delta_brightness()
            print(f"Brightness: {delta_brightness}")

        while delta_brightness > 0:
            self.lcd_thread.trigger_update_pos(0, -1)
            delta_brightness = self._measure_delta_brightness()
            print(f"Brightness: {delta_brightness}")

        self.lcd_thread.trigger_update_pos(0, 1)
        delta_brightness2 = self._measure_delta_brightness()
        print(f"Brightness: {delta_brightness2}")

        if abs(delta_brightness2) > abs(delta_brightness):
            self.lcd_thread.trigger_update_pos(0, -1)


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stream")
        self.label = QLabel(self)
        self.capture_btn = QPushButton("Capture")
        self.config_btn = QPushButton("Reload configuration")

        self.label.resize(640, 480)

        # Create thread
        self.video_thread = VideoThread(batch_size=4)
        self.image_handler_thread = ImageHandlerThread(self.video_thread.get_image_queue())
        self.image_handler_thread.change_pixmap_signal.connect(self.update_image)
        self.video_thread.error_signal.connect(self.close)
        self.video_thread.start()
        self.image_handler_thread.start()

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
        menu_layout.addLayout(pattern_layout)

        self.setLayout(layout)

        # self.capture_btn.clicked.connect(self.video_thread.trigger_save)
        # self.config_btn.clicked.connect(self.video_thread.trigger_reload)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_X:
            self.lcd_thread.trigger_none(True)
            while not self.video_thread.get_image_queue().empty():
                time.sleep(0.01)
            self.video_thread.set_image_batch_size(1)
            self.lcd_thread.trigger_split_x(-1)
        elif event.key() == Qt.Key_Y:
            self.lcd_thread.trigger_none(True)
            while not self.video_thread.get_image_queue().empty():
                time.sleep(0.01)
            self.video_thread.set_image_batch_size(1)
            self.lcd_thread.trigger_split_y(-1)
        elif event.key() == Qt.Key_C:
            self.lcd_thread.trigger_none(True)
            while not self.video_thread.get_image_queue().empty():
                time.sleep(0.01)
            self.video_thread.set_image_batch_size(1)
            self.lcd_thread.trigger_circular(-1)
        elif event.key() == Qt.Key_R:
            self.lcd_thread.trigger_reverse(-1)
        elif event.key() == Qt.Key_W:
            self.lcd_thread.trigger_update_pos(1, 0)
        elif event.key() == Qt.Key_S:
            self.lcd_thread.trigger_update_pos(-1, 0)
        elif event.key() == Qt.Key_A:
            self.lcd_thread.trigger_update_pos(0, -1)
        elif event.key() == Qt.Key_D:
            self.lcd_thread.trigger_update_pos(0, 1)
        elif event.key() == Qt.Key_O:
            self.lcd_thread.trigger_none(True)
            while not self.video_thread.get_image_queue().empty():
                time.sleep(0.01)
            self.video_thread.set_image_batch_size(4)
            self.lcd_thread.trigger_dpc_pattern(True)
            # self.thread = CaptureThread(self.video_thread, self.lcd_thread)
            # self.thread.start()
        elif event.key() == Qt.Key_Z:
            self.thread = AdjustThread(self.video_thread, self.image_handler_thread, self.lcd_thread)
            self.thread.start()
        elif event.key() == Qt.Key_1:
            self.image_handler_thread.trigger_display_processing(1)
        elif event.key() == Qt.Key_2:
            self.image_handler_thread.trigger_display_processing(2)
        elif event.key() == Qt.Key_3:
            self.image_handler_thread.trigger_display_processing(3)
        elif event.key() == Qt.Key_4:
            self.image_handler_thread.trigger_display_processing(4)
        elif event.key() == Qt.Key_5:
            self.image_handler_thread.trigger_display_processing(5)
        elif event.key() == Qt.Key_6:
            self.image_handler_thread.trigger_display_processing(6)
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
