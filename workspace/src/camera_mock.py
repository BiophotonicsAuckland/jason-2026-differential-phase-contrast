import PySpin
import numpy as np

class PySpinCamera():
    def __init__(self, camera_idx=0):
        self.cam = camera_idx

    def open(self):
        pass

    def close(self):
        pass

    def get_image_data(self) -> np.ndarray:
        return (np.random.random((800,800))*256).astype(np.uint8)


if __name__ == "__main__":
    camera = PySpinCamera(0)
    camera.open()
    print(camera.get_image_data())
    camera.close()
