import time

import numpy as np

class PySpinCamera():
    def __init__(self, camera_idx=0):
        self.cam = camera_idx
        self.frame_id = -1

    def open(self):
        pass

    def close(self):
        pass

    def get_image_data(self) -> tuple[np.ndarray, int]:
        time.sleep(1)
        self.frame_id += 1
        return (np.random.random((512,512))*256).astype(np.uint8), self.frame_id


if __name__ == "__main__":
    camera = PySpinCamera(0)
    camera.open()
    print(camera.get_image_data())
    camera.close()
