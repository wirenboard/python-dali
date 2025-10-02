import unittest

try:
    from unittest import mock
except ImportError:
    import mock

from dali.driver.wbdali import WBDALIDriver


class TestWBDALIDriver(unittest.TestCase):
    @mock.patch("aiomqtt.Client")
    def test_encode_frame_for_modbus(self, mock_client):
        driver = WBDALIDriver("123")

        frame_16 = mock.MagicMock()
        frame_16.__len__.return_value = 16
        frame_16.as_integer = 0x1234

        frame_24 = mock.MagicMock()
        frame_24.__len__.return_value = 24
        frame_24.as_integer = 0x123456

        frame_25 = mock.MagicMock()
        frame_25.__len__.return_value = 25
        frame_25.as_integer = 0x1234567

        frame_invalid = mock.MagicMock()
        frame_invalid.__len__.return_value = 32

        assert driver._encode_frame_for_modbus(frame_16) == 305397760
        assert driver._encode_frame_for_modbus(frame_24) == 305419777
        assert driver._encode_frame_for_modbus(frame_25) == 4886705026

        with self.assertRaises(ValueError):
            driver._encode_frame_for_modbus(frame_invalid)
