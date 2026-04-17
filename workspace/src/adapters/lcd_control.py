import serial
import time
from enum import Enum, auto

class LCDMode(Enum):
    SPLIT_IN_X = auto()
    SPLIT_IN_Y = auto()
    CIRCULAR = auto()

## TODO
def send_and_receive(arduino_serial, text):
    # Encode string to bytes and add newline
    arduino_serial.write(bytes(text + '\n', 'utf-8'))
    time.sleep(0.05) # Brief pause for Arduino to process
    return arduino_serial.readline().decode('utf-8').strip()

class LCDController:
    def __init__(self, port='/dev/ttyUSB0'):
        self.arduino_serial = serial.Serial(port=port, baudrate=9600, timeout=.1)
        self.x_center = 66
        self.y_center = 78

    ## TODO
    def configure(self):
        self.x_center = 0
        self.y_center = 0

    def update(self, mode, inner_radius, outer_radius, reverse=False):
        match mode:
            case LCDMode.SPLIT_IN_X:
                self._send(f"0,{self.x_center},{self.y_center},{inner_radius},{outer_radius}") if not reverse else self._send(f"0,{-self.x_center},{self.y_center},{inner_radius},{outer_radius}")
            case LCDMode.SPLIT_IN_Y:
                self._send(f"1,{self.x_center},{self.y_center},{inner_radius},{outer_radius}") if not reverse else self._send(f"1,{self.x_center},{-self.y_center},{inner_radius},{outer_radius}")
            case LCDMode.CIRCULAR:
                self._send(f"-1,{self.x_center},{self.y_center},{inner_radius},{outer_radius}")
            case _:
                raise ValueError("The provided pattern mode for LCD is invalid")

    def update_center(self, change_x, change_y):
        self.x_center += change_x
        self.y_center += change_y

        print(f"New position: ({self.x_center}, {self.y_center})")

    def _send(self, text):
        self.arduino_serial.write(bytes(text + '\n', 'utf-8'))
        line = self.arduino_serial.readline().decode('utf-8').rstrip()
        assert line.startswith('0'), f"{line}"

    def close(self):
        self.arduino_serial.close()
