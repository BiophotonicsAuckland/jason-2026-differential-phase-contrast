import serial
from serial.tools import list_ports
import time
from enum import Enum, auto


class LCDMode(Enum):
    NONE = auto()
    SPLIT_IN_X = auto()
    SPLIT_IN_Y = auto()
    CIRCULAR = auto()
    DPC_PATTERN = auto()

# TODO


def send_and_receive(arduino_serial, text):
    # Encode string to bytes and add newline
    arduino_serial.write(bytes(text + '\n', 'utf-8'))
    time.sleep(0.05)  # Brief pause for Arduino to process
    return arduino_serial.readline().decode('utf-8').strip()


class LCDController:
    def __init__(self, port=None):
        if not port:
            port = LCDController._get_uc_port()
            if not port:
                raise ConnectionError("Cannot find LCD port")

        self.arduino_serial = serial.Serial(port=port, baudrate=115200, timeout=1)
        # print(f"The board reads {self.arduino_serial.readline()}")
        self.x_center = 64
        self.y_center = 77

    def _get_uc_port():
        ports = list(list_ports.comports())
        for port in ports:
            ## Windows 
            # Description: Silicon Labs CP210x USB to UART Bridge (COM3)
            # Hardware ID: USB VID:PID=10C4:EA60 SER=0001 LOCATION=1-4
            if (port.interface and 'CP2102' in port.interface) or (port.description and 'UART' in port.description):
                return port.device
        
        return None
        
    # TODO
    def configure(self):
        self.x_center = 0
        self.y_center = 0

    def update(self, mode, inner_radius, outer_radius, reverse, frame_count):
        match mode:
            case LCDMode.NONE:
                self._send(f"0,{self.x_center},{self.y_center},{inner_radius},{outer_radius},{frame_count}")
            case LCDMode.SPLIT_IN_X:
                self._send(f"1,{self.x_center},{self.y_center},{inner_radius},{outer_radius},{frame_count}") if not reverse else self._send(
                    f"1,{-self.x_center},{self.y_center},{inner_radius},{outer_radius},{frame_count}")
            case LCDMode.SPLIT_IN_Y:
                self._send(f"2,{self.x_center},{self.y_center},{inner_radius},{outer_radius},{frame_count}") if not reverse else self._send(
                    f"2,{self.x_center},{-self.y_center},{inner_radius},{outer_radius},{frame_count}")
            case LCDMode.CIRCULAR:
                self._send(f"3,{self.x_center},{self.y_center},{inner_radius},{outer_radius},{frame_count}")
            case LCDMode.DPC_PATTERN:
                self._send(f"4,{self.x_center},{self.y_center},{inner_radius},{outer_radius},{frame_count}")
            case _:
                raise ValueError("The provided pattern mode for LCD is invalid")

    def update_center(self, change_x, change_y):
        self.x_center += change_x
        self.y_center += change_y

        print(f"New position: ({self.x_center}, {self.y_center})")

    def _send(self, text):
        self.arduino_serial.write(bytes(text + '\n', 'utf-8'))
        line = ''
        while not line.startswith('0'):
            line = self.arduino_serial.readline().decode('utf-8').rstrip()
            time.sleep(0.1)
            print(line)
        # time.sleep(0.01) #TODO there seems to be some painting delay

    def close(self):
        self.arduino_serial.close()


if __name__ == "__main__":
    lcd_controller = LCDController()
    import time
    time.sleep(2)
    lcd_controller.update(LCDMode.SPLIT_IN_X, 0, 50, True, 0)
    # time.sleep(0.1)
    lcd_controller.update(LCDMode.SPLIT_IN_X, 0, 50, False, 0)
    lcd_controller.close()
