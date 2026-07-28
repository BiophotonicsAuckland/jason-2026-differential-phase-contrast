from queue import Queue
import queue
import time
import os
import sys
import threading
from datetime import datetime

from PyQt5.QtCore import QThread, pyqtSignal, Qt, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QHBoxLayout, QVBoxLayout, QPushButton, QWidget
import numpy as np
import cv2
import pyqtgraph as pg

from core.config import AppConfigManager
from adapters.lcd.lcd_control import LCDMode
from optics import FDSPIOptimized, differential_phase_contrast, normalize


class VideoThread(QThread):
    error_signal = pyqtSignal(str)

    def __init__(self, camera_impl, batch_size=1):
        super().__init__()
        self._run_flag = True
        self.camera = camera_impl  # PySpinCamera(0)
        self.camera.open()

        self._batch_size = batch_size
        self._exit_ready_flag = threading.Event()
        self.img_queue = Queue()
        self._img_batch = [None, None, None, None, 0]
        self._next_frame_id = 0
        self._batch_start_frame_id = 0

    def _get_img_index_in_batch(self, frame_id):
        return (frame_id % self._batch_size - self._batch_start_frame_id % self._batch_size) % self._batch_size

    def run(self):
        if self.camera.cam is None:
            self._exit_ready_flag.set()
            self.error_signal.emit("Camera cannot be found")
            return

        while self._run_flag:
            img, frame_id = self.camera.get_image_data()
            if img is not None:
                if frame_id == self._next_frame_id:
                    self._img_batch[self._get_img_index_in_batch(frame_id)] = img
                    self._img_batch[4] += 1
                    self._next_frame_id += 1
                    if self._img_batch[4] >= 4:
                        self.img_queue.put(self._img_batch[:-1])
                else:
                    self._img_batch = [None, None, None, None, 0]
                    self._next_frame_id = frame_id + 1
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


class ImageHandlerThread(QThread):
    change_pixmap_signal = pyqtSignal(QImage, np.ndarray)

    def __init__(self, image_queue: Queue[np.ndarray]):
        super().__init__()
        self._run_flag = True
        self._input_image_queue = image_queue
        self.output_image_queue = queue.Queue(1)
        self.process_fun = lambda imgs: imgs[0]
        self.processors = {}

    def run(self):
        while self._run_flag:
            try:
                imgs = self._input_image_queue.get(timeout=1)
            except queue.Empty:
                continue

            img = self.process_fun(imgs)

            if self.output_image_queue.empty():
                self.output_image_queue.put(img)

            h, w = img.shape
            bytes_per_line = int(w if img.dtype == np.uint8 else 2*w)
            convert_to_Qt_format = QImage(
                img.data, w, h, bytes_per_line,
                QImage.Format_Grayscale8 if img.dtype == np.uint8 else QImage.Format_Grayscale16)
            pixelmap = convert_to_Qt_format.scaled(
                512, 512, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

            hist = cv2.calcHist([img], [0], None, [256], [0, 256 if img.dtype == np.uint8 else 65536])

            self.change_pixmap_signal.emit(pixelmap, hist[:, 0])

    def trigger_display_processing(self, mode: int):
        if mode <= 4:
            self.process_fun = lambda imgs: imgs[min(mode, len(imgs))-1]  # TODO: it doesn't work
        elif mode == 5:
            self.process_fun = lambda imgs: normalize(differential_phase_contrast(imgs[0], imgs[1]), imgs[0].dtype)
        elif mode == 6:
            self.process_fun = lambda imgs: normalize(differential_phase_contrast(imgs[2], imgs[3]), imgs[0].dtype)
        elif mode == 7:
            if "FDSPI" not in self.processors:
                self.processors = {"FDSPI": FDSPIOptimized()}
            self.process_fun = lambda imgs: normalize(self.processors["FDSPI"](differential_phase_contrast(
                imgs[0], imgs[1]), -differential_phase_contrast(imgs[2], imgs[3])), imgs[0].dtype)

    @pyqtSlot()
    def trigger_measure_brightness(self, result_queue):
        def measure_brightness_process_fun(ims):
            scaling = 1/255 if ims[0].dtype == np.uint8 else 1/65535
            result_queue.put((ims[0]*scaling).sum())
            return ims[0]

        time.sleep(0.4)
        self.process_fun = measure_brightness_process_fun


class LCDControlThread(QThread):
    def __init__(self, lcd_controller_impl):
        super().__init__()
        self._reverse = False
        self._lcd_controller = lcd_controller_impl
        self._update_pending = False
        self._lcd_mode = LCDMode.CIRCULAR
        self._run_flag = True
        self._exit_ready_flag = threading.Event()
        self._update_queue = Queue()
        self._frame_count = -1
        self.outer_radius = 50
        self.update_callback = lambda: self._lcd_controller.update(
            self._lcd_mode, 0, self.outer_radius, self._reverse, self._frame_count)

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
    def __init__(self, image_handler_thread: ImageHandlerThread, lcd_thread: LCDControlThread):
        super().__init__()
        self.image_handler_thread = image_handler_thread
        self.lcd_thread = lcd_thread

    def run(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        working_dir = AppConfigManager.config.image_acquisition.image_save_dir
        os.makedirs(working_dir, exist_ok=True)

        try:
            # clear stale image
            img = self.image_handler_thread.output_image_queue.get(timeout=1)
            img = self.image_handler_thread.output_image_queue.get(timeout=1)
            print(img.shape)
            cv2.imwrite(working_dir/f"{timestamp}.tiff", img, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
            print(f'Image saved: {working_dir/f"{timestamp}.tiff"}')
        except queue.Empty:
            pass


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

    def _measure_brightness(self):
        result_queue = Queue(1)

        self.img_handler_thread.trigger_measure_brightness(result_queue)
        self.lcd_thread.trigger_circular(1, True)
        return result_queue.get()

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

        # Radius auto adjustment
        self.lcd_thread.outer_radius = 5
        prev_brightness = float('-inf')
        brightness = 0
        while brightness > prev_brightness:
            prev_brightness = brightness
            self.lcd_thread.outer_radius += 2
            print(f"New radius: {self.lcd_thread.outer_radius}")
            brightness = self._measure_brightness()
            print(f"Brightness: {brightness}")

        prev_brightness = brightness
        while brightness >= prev_brightness:
            prev_brightness = brightness
            self.lcd_thread.outer_radius -= 1
            print(f"New radius: {self.lcd_thread.outer_radius}")
            brightness = self._measure_brightness()
            print(f"Brightness: {brightness}")

        self.lcd_thread.outer_radius += 1
        print(f"New radius: {self.lcd_thread.outer_radius}")
        brightness = self._measure_brightness()
        print(f"Brightness: {brightness}")


class HistogramCanvas(pg.PlotWidget):
    """A matplotlib canvas integrated into the PyQt ecosystem."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.graph = self.plot(
            stepMode="center",     # Connects points as histogram bins
            fillLevel=0,          # Fills the area down to y=0
            fillOutline=True,     # Draws an explicit outline around the shape
            brush=(0, 100, 255, 150),  # RGBA fill color (Semi-transparent blue)
            pen=pg.mkPen('w', width=1.5)  # White outline border
        )

    def plot_histogram(self, hist):
        self.graph.setData(np.arange(len(hist)+1), hist)


class App(QWidget):
    def __init__(self, camera_impl, lcd_controller_impl):
        super().__init__()
        self.setWindowTitle("Stream")
        self.label = QLabel(self)
        self.capture_btn = QPushButton("Capture")
        self.config_btn = QPushButton("Reload configuration")

        self.hist_canvas = HistogramCanvas(self)
        # self.label.setScaledContents(True)

        # Create thread
        self.video_thread = VideoThread(camera_impl, batch_size=4)
        self.image_handler_thread = ImageHandlerThread(self.video_thread.get_image_queue())
        self.image_handler_thread.change_pixmap_signal.connect(self.update_image)
        self.video_thread.error_signal.connect(self.close)
        self.video_thread.start()
        self.image_handler_thread.start()

        self.lcd_thread = LCDControlThread(lcd_controller_impl)
        self.lcd_thread.start()

        self.thread = None

        layout = QHBoxLayout()

        container = QWidget()
        container.setMinimumSize(200, 300)
        menu_layout = QVBoxLayout(container)
        layout.addWidget(self.label)
        menu_layout.setSpacing(10)
        menu_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(container)

        menu_layout.addStretch(1)
        menu_layout.addWidget(self.hist_canvas, stretch=4)
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
            self.image_handler_thread.trigger_display_processing(1)
            self.lcd_thread.trigger_none(True)
            while not self.video_thread.get_image_queue().empty():
                time.sleep(0.01)
            self.video_thread.set_image_batch_size(1)
            self.lcd_thread.trigger_split_x(-1)
        elif event.key() == Qt.Key_Y:
            self.image_handler_thread.trigger_display_processing(1)
            self.lcd_thread.trigger_none(True)
            while not self.video_thread.get_image_queue().empty():
                time.sleep(0.01)
            self.video_thread.set_image_batch_size(1)
            self.lcd_thread.trigger_split_y(-1)
        elif event.key() == Qt.Key_C:
            self.image_handler_thread.trigger_display_processing(1)
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
            self.image_handler_thread.trigger_display_processing(1)
            self.lcd_thread.trigger_none(True)
            while not self.video_thread.get_image_queue().empty():
                time.sleep(0.01)
            self.video_thread.set_image_batch_size(4)
            self.lcd_thread.trigger_dpc_pattern(True)
        elif event.key() == Qt.Key_P:
            self.thread = CaptureThread(self.image_handler_thread, self.lcd_thread)
            self.thread.start()
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
        elif event.key() == Qt.Key_7:
            self.image_handler_thread.trigger_display_processing(7)
        else:
            pass

    def update_image(self, qt_img, hist):
        """Updates the image_label with a new image"""
        self.label.setPixmap(QPixmap.fromImage(qt_img))
        self.hist_canvas.plot_histogram(hist)

    def closeEvent(self, event):
        self.video_thread.stop()
        self.lcd_thread.stop()
        # we tell the OS it's okay to hide the window.
        event.accept()


if __name__ == "__main__":
    from adapters.camera.camera_mock import PySpinCamera
    from adapters.lcd.lcd_mock import LCDController
    
    app = QApplication(sys.argv)
    a = App(PySpinCamera(), LCDController())
    a.show()
    sys.exit(app.exec_())