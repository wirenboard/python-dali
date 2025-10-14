import asyncio
import json
import unittest

try:
    from unittest.mock import AsyncMock, MagicMock, Mock, patch
except ImportError:
    from mock import AsyncMock, MagicMock, Mock, patch

from dali.command import Command, Response
from dali.driver.wbdali import WBDALIConfig, WBDALIDriver
from dali.frame import BackwardFrame, ForwardFrame


class MockCommand(Command):
    def __init__(self, sendtwice=False, response_class=None):
        self.sendtwice = sendtwice
        self.response = response_class
        self.frame = ForwardFrame([0x12, 0x34])

    def __str__(self):
        return "MockCommand"


class MockResponse(Response):
    def __init__(self, frame):
        self.frame = frame
        self.data = frame.as_integer if frame else None


class TestWBDALIDriver(unittest.TestCase):
    def setUp(self):
        self.config = WBDALIConfig(
            modbus_port_path="/dev/ttyRS485-1",
            device_name="wb-mdali",
            mqtt_host="localhost",
            mqtt_port=1883,
        )

    @patch("aiomqtt.Client")
    def test_encode_frame_for_modbus(self, mock_client):
        driver = WBDALIDriver(self.config)

        frame_16 = MagicMock()
        frame_16.__len__.return_value = 16
        frame_16.as_integer = 0x1234

        frame_24 = MagicMock()
        frame_24.__len__.return_value = 24
        frame_24.as_integer = 0x123456

        frame_25 = MagicMock()
        frame_25.__len__.return_value = 25
        frame_25.as_integer = 0x1234567

        frame_invalid = MagicMock()
        frame_invalid.__len__.return_value = 32

        assert driver._encode_frame_for_modbus(frame_16) == 305397760
        assert driver._encode_frame_for_modbus(frame_24) == 305419777
        assert driver._encode_frame_for_modbus(frame_25) == 4886705026

        with self.assertRaises(ValueError):
            driver._encode_frame_for_modbus(frame_invalid)

    @patch("aiomqtt.Client")
    @patch("asyncio.get_event_loop")
    async def test_send_command_without_response(self, mock_get_loop, mock_mqtt_client_class):
        mock_loop = AsyncMock()
        mock_get_loop.return_value = mock_loop

        mock_mqtt_client = AsyncMock()
        mock_mqtt_client._connected = asyncio.Event()
        mock_mqtt_client._connected.set()
        mock_mqtt_client.publish = AsyncMock()
        mock_mqtt_client_class.return_value = mock_mqtt_client

        driver = WBDALIDriver(self.config)
        driver.bus_traffic._invoke = MagicMock()

        driver.send_barrier = AsyncMock()
        driver.send_barrier.wait = AsyncMock(return_value=(0, [(0, 0x12340000)]))
        driver.next_pointer = 0

        cmd = MockCommand(sendtwice=False, response_class=None)

        mock_future = AsyncMock()
        with patch.object(driver, "get_next_pointer", return_value=(0, mock_future)):
            with patch.object(driver, "_add_cmd_to_send_buffer", new_callable=AsyncMock) as mock_add_cmd:
                result = await driver.send(cmd)
                self.assertIsNone(result)
                mock_add_cmd.assert_called_once()
                driver.bus_traffic._invoke.assert_called_once_with(cmd, None, False)

    @patch("aiomqtt.Client")
    @patch("asyncio.get_event_loop")
    async def test_send_command_with_response(self, mock_get_loop, mock_mqtt_client_class):
        mock_loop = AsyncMock()
        mock_get_loop.return_value = mock_loop

        mock_mqtt_client = AsyncMock()
        mock_mqtt_client._connected = asyncio.Event()
        mock_mqtt_client._connected.set()
        mock_mqtt_client.publish = AsyncMock()
        mock_mqtt_client_class.return_value = mock_mqtt_client

        driver = WBDALIDriver(self.config)
        driver.bus_traffic._invoke = MagicMock()

        driver.send_barrier = AsyncMock()
        driver.send_barrier.wait = AsyncMock(return_value=(0, [(0, 0x12340000)]))
        driver.next_pointer = 0

        cmd = MockCommand(sendtwice=False, response_class=MockResponse)

        response_frame = BackwardFrame(0x56)
        mock_future = AsyncMock()
        mock_future.__await__ = lambda: iter([response_frame])

        with patch.object(driver, "get_next_pointer", return_value=(0, mock_future)):
            with patch.object(driver, "_add_cmd_to_send_buffer", new_callable=AsyncMock) as mock_add_cmd:
                result = await driver.send(cmd)
                self.assertIsInstance(result, MockResponse)
                self.assertEqual(result.data, 0x56)
                mock_add_cmd.assert_called_once()
                driver.bus_traffic._invoke.assert_called_once_with(cmd, result, False)

    @patch("aiomqtt.Client")
    async def test_send_command_sendtwice_with_response_raises_error(self, mock_mqtt_client_class):
        mock_mqtt_client = AsyncMock()
        mock_mqtt_client_class.return_value = mock_mqtt_client

        driver = WBDALIDriver(self.config)

        cmd = MockCommand(sendtwice=True, response_class=MockResponse)

        with self.assertRaises(ValueError) as context:
            await driver.send(cmd)

        self.assertIn("Command with sendtwice=True cannot have a response", str(context.exception))

    @patch("aiomqtt.Client")
    @patch("asyncio.get_event_loop")
    async def test_send_command_sendtwice_without_response(self, mock_get_loop, mock_mqtt_client_class):
        mock_loop = AsyncMock()
        mock_get_loop.return_value = mock_loop

        mock_mqtt_client = AsyncMock()
        mock_mqtt_client._connected = asyncio.Event()
        mock_mqtt_client._connected.set()
        mock_mqtt_client.publish = AsyncMock()
        mock_mqtt_client_class.return_value = mock_mqtt_client

        driver = WBDALIDriver(self.config)
        driver.bus_traffic._invoke = MagicMock()

        cmd = MockCommand(sendtwice=True, response_class=None)

        mock_future1 = AsyncMock()
        mock_future2 = AsyncMock()

        with patch.object(
            driver,
            "get_next_pointer",
            side_effect=[(0, mock_future1), (1, mock_future2)],
        ):
            with patch.object(driver, "_add_cmd_to_send_buffer", new_callable=AsyncMock) as mock_add_cmd:
                result = await driver.send(cmd)
                self.assertIsNone(result)
                self.assertEqual(mock_add_cmd.call_count, 2)
                driver.bus_traffic._invoke.assert_called_once_with(cmd, None, False)

    @patch("aiomqtt.Client")
    async def test_add_cmd_to_send_buffer_single_command(self, mock_mqtt_client_class):
        mock_mqtt_client = AsyncMock()
        mock_mqtt_client._connected = asyncio.Event()
        mock_mqtt_client._connected.set()
        mock_mqtt_client.publish = AsyncMock()
        mock_mqtt_client_class.return_value = mock_mqtt_client

        driver = WBDALIDriver(self.config)
        driver.rpc_id_counter = 0

        driver.send_barrier = AsyncMock()
        driver.send_barrier.wait = AsyncMock(return_value=(0, [(5, 0x12340000)]))

        await driver._add_cmd_to_send_buffer(5, 0x12340000)

        mock_mqtt_client.publish.assert_called_once()

        call_args = mock_mqtt_client.publish.call_args
        topic, payload = call_args[0]
        self.assertEqual(topic, "/rpc/v1/wb-mqtt-serial/port/Load/dali-no-response")
        payload_data = json.loads(payload)
        self.assertEqual(payload_data["id"], 1)
        self.assertEqual(payload_data["params"]["slave_id"], driver.config.modbus_slave_id)
        self.assertEqual(payload_data["params"]["function"], 16)
        self.assertEqual(payload_data["params"]["address"], 1920 + 5 * 2)
        self.assertEqual(payload_data["params"]["count"], 2)
        self.assertEqual(payload_data["params"]["msg"], "12340000")
        self.assertEqual(payload_data["params"]["protocol"], "modbus")
        self.assertEqual(payload_data["params"]["format"], "HEX")

    @patch("aiomqtt.Client")
    async def test_add_cmd_to_send_buffer_multiple_consecutive_commands(self, mock_mqtt_client_class):
        mock_mqtt_client = AsyncMock()
        mock_mqtt_client._connected = asyncio.Event()
        mock_mqtt_client._connected.set()
        mock_mqtt_client.publish = AsyncMock()
        mock_mqtt_client_class.return_value = mock_mqtt_client

        driver = WBDALIDriver(self.config)
        driver.rpc_id_counter = 0

        driver.send_barrier = AsyncMock()
        driver.send_barrier.wait = AsyncMock(
            return_value=(0, [(5, 0x12340000), (6, 0x56780000), (7, 0x9ABC0000)])
        )

        await driver._add_cmd_to_send_buffer(5, 0x12340000)
        mock_mqtt_client.publish.assert_called_once()

        call_args = mock_mqtt_client.publish.call_args
        topic, payload = call_args[0]
        payload_data = json.loads(payload)
        self.assertEqual(payload_data["params"]["address"], 1920 + 5 * 2)
        self.assertEqual(payload_data["params"]["count"], 6)
        self.assertEqual(payload_data["params"]["msg"], "123400005678000056bc0000")

    @patch("aiomqtt.Client")
    async def test_add_cmd_to_send_buffer_non_consecutive_commands(self, mock_mqtt_client_class):
        mock_mqtt_client = AsyncMock()
        mock_mqtt_client._connected = asyncio.Event()
        mock_mqtt_client._connected.set()
        mock_mqtt_client.publish = AsyncMock()
        mock_mqtt_client_class.return_value = mock_mqtt_client

        driver = WBDALIDriver(self.config)
        driver.rpc_id_counter = 0

        driver.send_barrier = AsyncMock()
        driver.send_barrier.wait = AsyncMock(
            return_value=(
                0,
                [(5, 0x12340000), (8, 0x56780000)],
            )
        )

        with patch.object(driver, "send_modbus_rpc_no_response", new_callable=AsyncMock) as mock_send_modbus:
            await driver._add_cmd_to_send_buffer(5, 0x12340000)
            self.assertEqual(mock_send_modbus.call_count, 2)

            first_call = mock_send_modbus.call_args_list[0]
            self.assertEqual(first_call.kwargs["address"], 1920 + 5 * 2)
            self.assertEqual(first_call.kwargs["count"], 2)
            self.assertEqual(first_call.kwargs["msg"], "12340000")

            second_call = mock_send_modbus.call_args_list[1]
            self.assertEqual(second_call.kwargs["address"], 1920 + 8 * 2)
            self.assertEqual(second_call.kwargs["count"], 2)
            self.assertEqual(second_call.kwargs["msg"], "56780000")

    @patch("aiomqtt.Client")
    async def test_send_modbus_rpc_no_response_mqtt_publish(self, mock_mqtt_client_class):
        mock_mqtt_client = AsyncMock()
        mock_mqtt_client._connected = asyncio.Event()
        mock_mqtt_client._connected.set()
        mock_mqtt_client.publish = AsyncMock()
        mock_mqtt_client_class.return_value = mock_mqtt_client

        driver = WBDALIDriver(self.config)
        driver.rpc_id_counter = 42

        await driver.send_modbus_rpc_no_response(function=16, address=1930, count=4, msg="1234567890abcdef")

        mock_mqtt_client.publish.assert_called_once()

        call_args = mock_mqtt_client.publish.call_args
        topic, payload = call_args[0]

        expected_topic = "/rpc/v1/wb-mqtt-serial/port/Load/dali-no-response"
        self.assertEqual(topic, expected_topic)

        payload_data = json.loads(payload)
        expected_payload = {
            "params": {
                "slave_id": self.config.modbus_slave_id,
                "function": 16,
                "address": 1930,
                "count": 4,
                "frame_timeout": 0,
                "protocol": "modbus",
                "format": "HEX",
                "path": self.config.modbus_port_path,
                "baud_rate": self.config.modbus_baud_rate,
                "parity": self.config.modbus_parity,
                "data_bits": self.config.modbus_data_bits,
                "stop_bits": self.config.modbus_stop_bits,
                "msg": "1234567890abcdef",
            },
            "id": 43,
        }

        self.assertEqual(payload_data, expected_payload)
        self.assertEqual(driver.rpc_id_counter, 43)

    @patch("aiomqtt.Client")
    async def test_send_modbus_rpc_mqtt_connection_timeout(self, mock_mqtt_client_class):
        mock_mqtt_client = AsyncMock()
        mock_mqtt_client._connected = AsyncMock()
        mock_mqtt_client._connected.__await__ = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_mqtt_client_class.return_value = mock_mqtt_client

        driver = WBDALIDriver(self.config)

        with self.assertRaises(asyncio.TimeoutError):
            await driver.send_modbus_rpc_no_response(
                function=16, address=1930, count=4, msg="1234567890abcdef"
            )
