from PyQt5.QtWidgets import QApplication

import sys

from adapters.camera.camera import PySpinCamera
from adapters.lcd.lcd_control import LCDController
from ui.acquire_and_display import App

if __name__ == "__main__":
    camera_impl = PySpinCamera()
    lcd_impl = LCDController()

    app = QApplication(sys.argv)
    a = App(camera_impl, lcd_impl)
    a.show()
    sys.exit(app.exec_())