import PySpin
import numpy as np

from core.config import AppConfigManager


class PySpinCamera():
    def __init__(self, camera_idx=0):
        self.camera_idx = camera_idx
        self.system: PySpin.System = PySpin.System.GetInstance()
        self.cam: PySpin.CameraPtr = None
        self.cam_list: PySpin.CameraList = None
        self.is_acquisiting = False
        self._img_processor = PySpin.ImageProcessor()

    def configure(self):
        AppConfigManager.load_config()
        config = AppConfigManager.config.camera
        self._set_attribute_value(self.cam.ExposureTime, float(config.attributes['ExposureTime']))
        self._set_attribute_value(self.cam.Width, int(config.attributes['Width']))
        self._set_attribute_value(self.cam.Height, int(config.attributes['Height']))
        self._set_attribute_value(self.cam.OffsetX, int(config.attributes['OffsetX']))
        self._set_attribute_value(self.cam.OffsetY, int(config.attributes['OffsetY']))
        self._set_attribute_value(self.cam.AcquisitionFrameRate, float(config.attributes['AcquisitionFrameRate']))


    def open(self):
        # Retrieve list of cameras from the system
        self.cam_list = self.system.GetCameras()

        num_cameras = self.cam_list.GetSize()

        print(f'Number of cameras detected: {num_cameras}')

        # Finish if there are no cameras
        if num_cameras == 0:
            self.cam_list.Clear()
            self.system.ReleaseInstance()
            print('Not enough cameras!')
            return None

        self.cam = self.cam_list[self.camera_idx]
        self.cam.Init()

        # Turn off auto adjustment on the camera
        for i in [self.cam.AutoExposureTargetGreyValueAuto, self.cam.ExposureAuto, self.cam.GainAuto]:
            i.SetValue(0)

        # self._set_attribute_value(
        #     self.cam.TLStream.StreamBufferHandlingMode, 'NewestOnly')
        # self._set_attribute_value(self.cam.AcquisitionMode, 'Continuous')
        self._set_attribute_value(self.cam.TriggerMode, 'Off')
        self._set_attribute_value(self.cam.TriggerSource, 'Line0')
        self._set_attribute_value(self.cam.TriggerOverlap, 'ReadOut')
        self._set_attribute_value(self.cam.AcquisitionMode, 'Continuous')
        self._set_attribute_value(self.cam.TriggerMode, 'On')
        self._set_attribute_value(self.cam.TLStream.StreamBufferCountMode, 'Manual')
        self._set_attribute_value(self.cam.TLStream.StreamBufferCountManual, 50)
        self._set_attribute_value(self.cam.TLStream.StreamBufferHandlingMode, 'OldestFirst')
        self._set_attribute_value(self.cam.OffsetX, 0)
        self._set_attribute_value(self.cam.OffsetY, 0)
        # self._set_attribute_value(self.cam.Width, 2048)
        # self._set_attribute_value(self.cam.Height, 2048)
        # self._set_attribute_value(self.cam.OffsetX, 200)
        # self._set_attribute_value(self.cam.OffsetY, 0)

        self._set_attribute_value(self.cam.PixelFormat, 'Mono16')
        # self._set_attribute_value(self.cam.PixelFormat, 'Mono8')
        self._set_attribute_value(self.cam.AcquisitionFrameRateEnable, True)
        self.configure()
        # self._set_attribute_value(self.cam.TLStream.StreamBufferCountManual, 3)
        # self._set_attribute_value(self.cam.DeviceLinkThroughputLimit, 200000000)

        print(self.cam.TLStream.StreamAnnouncedBufferCount.GetValue())
        # print(PySpinCamera._print_node(self.cam.PixelFormat))
        # print(self.cam.TLStream.StreamBufferCountManual.GetMin())
        # print(self.cam.TLStream.StreamBufferCountManual.GetMax())

        # print(print_node(self.cam.AutoExposureTargetGreyValueAuto))
        # print(print_node(self.cam.ExposureAuto))
        # print(print_node(self.cam.GainAuto))

    def close(self):
        if self.is_acquisiting:
            self.cam.EndAcquisition()
        # Release reference to camera
        # NOTE: Unlike the C++ examples, we cannot rely on pointer objects being automatically
        # cleaned up when going out of scope.
        # The usage of del is preferred to assigning the variable to None.
        if self.cam:
            self.cam.DeInit()
        del self.cam

        # Clear camera list before releasing system
        self.cam_list.Clear()

        # Release system instance
        self.system.ReleaseInstance()

    def get_image_data(self) -> np.ndarray:
        if not self.is_acquisiting:
            self.is_acquisiting = True
            self.cam.BeginAcquisition()

        image_data = None
        try:
            image_result = self.cam.GetNextImage(1000)

            if image_result.IsIncomplete():
                print(
                    f'Image incomplete with image status {image_result.GetImageStatus()}')
                image_result.Release()
                return image_data

            frame_id = image_result.GetFrameID()

            if image_result.GetPixelFormatName() == 'Mono8':
                image_data = image_result.GetNDArray()
            else:
                image_converted = self._img_processor.Convert(image_result, PySpin.PixelFormat_Mono16)
                image_data = image_converted.GetNDArray()
                image_converted.Release()

            image_result.Release()
            return image_data, frame_id
        except PySpin.SpinnakerException:
            return None, 0

    def _set_attribute_value(self, attr, value):
        match value:
            case str():
                attr_ptr = PySpin.CEnumerationPtr(attr)
                assert PySpin.IsReadable(attr_ptr) and PySpin.IsWritable(
                    attr_ptr), 'Unable to modify attribute.. Aborting...'
                value_ptr = attr_ptr.GetEntryByName(value)
                assert PySpin.IsReadable(
                    value_ptr), f'Unable to set value to {value}.. Aborting...'
                attr_ptr.SetIntValue(value_ptr.GetValue())
                return
            case bool():
                attr_ptr = PySpin.CBooleanPtr(attr)
            case float():
                attr_ptr = PySpin.CFloatPtr(attr)
            case int():
                attr_ptr = PySpin.CIntegerPtr(attr)
            case _:
                attr_ptr = None

        assert PySpin.IsReadable(attr_ptr) and PySpin.IsWritable(
            attr_ptr), 'Unable to modify attribute.. Aborting...'
        attr_ptr.SetValue(value)

    def _print_node(node):
        return f"{node.GetDisplayName()}:\nDefault:{node.GetValue()}\n{PySpinCamera._get_entries(node)}"

    def _get_entries(node):
        entries = node.GetEntries()

        possible_values = []
        for entry in entries:
            # Cast to CEnumEntry
            enum_entry = PySpin.CEnumEntryPtr(entry)
            if PySpin.IsAvailable(enum_entry) and PySpin.IsReadable(enum_entry):
                # 4. Get symbolic name
                possible_values.append(enum_entry.GetSymbolic())

        return possible_values


if __name__ == "__main__":
    camera = PySpinCamera(0)
    camera.open()
    camera.close()
