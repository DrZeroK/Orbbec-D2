"""Mock the native read-only serial ABI; never load a native DLL or open USB."""
import ctypes as c
import unittest
from unittest.mock import Mock,patch
import d2_camera as d2


class FactorySerialTests(unittest.TestCase):
    def test_only_known_serial_getter_is_used_and_handles_close_on_mismatch(self):
        for expected,rc in ((d2.FACTORY_SERIAL,0),('wrong-device',0),(d2.FACTORY_SERIAL,4)):
            with self.subTest(expected=expected,rc=rc):
                sdk = Mock()
                sdk.oniInitialize.return_value = 0
                devices = (d2.DeviceInfo*1)()
                devices[0].uri,devices[0].vid,devices[0].pid = b'synthetic-device',0x2bc5,0x060d
                def listed(out,count):
                    c.cast(out,c.POINTER(c.POINTER(d2.DeviceInfo)))[0] = c.cast(devices,c.POINTER(d2.DeviceInfo))
                    c.cast(count,c.POINTER(c.c_int))[0] = 1
                    return 0
                def opened(uri,out):
                    c.cast(out,c.POINTER(d2.P))[0] = d2.P(7)
                    return 0
                def getter(device,prop,buffer,length):
                    self.assertEqual(prop,3)
                    payload = d2.FACTORY_SERIAL.encode()+b'\0'
                    c.memmove(buffer,payload,len(payload))
                    c.cast(length,c.POINTER(c.c_int))[0] = len(payload)
                    return rc
                sdk.oniGetDeviceList.side_effect = listed
                sdk.oniDeviceOpen.side_effect = opened
                sdk.oniDeviceGetProperty.side_effect = getter
                with patch('d2_camera.c.CDLL',return_value=sdk):
                    if expected == d2.FACTORY_SERIAL and rc == 0:
                        d2.verify_factory_device('/synthetic',expected)
                    else:
                        with self.assertRaises(RuntimeError):
                            d2.verify_factory_device('/synthetic',expected)
                sdk.oniDeviceGetProperty.assert_called_once()
                sdk.oniDeviceClose.assert_called_once()
                sdk.oniReleaseDeviceList.assert_called_once()
                sdk.oniShutdown.assert_called_once()

    def test_pending_native_read_is_never_closed_concurrently(self):
        camera = d2.D2Camera('/synthetic')
        camera.sdk,camera.device,camera._thread = Mock(),d2.P(7),Mock()
        camera._thread.is_alive.return_value = True
        with self.assertRaises(RuntimeError):
            camera.__exit__()
        camera.sdk.d2_close.assert_not_called()


if __name__ == '__main__':
    unittest.main()
