import unittest
from unittest.mock import MagicMock, patch

from tascam_controller import TascamController


class TascamControllerConnectTests(unittest.TestCase):
    @patch("tascam_controller.threading.Thread")
    @patch.object(TascamController, "_send_command_now", return_value=True)
    @patch("tascam_controller.serial.Serial")
    def test_connect_starts_threads_only_once(self, serial_cls, _send_now, thread_cls):
        thread_1 = MagicMock()
        thread_2 = MagicMock()
        thread_cls.side_effect = [thread_1, thread_2]
        serial_handle = MagicMock()
        serial_handle.is_open = True
        serial_cls.return_value = serial_handle

        controller = TascamController(port="/dev/null", baudrate=9600)

        first = controller.connect()
        second = controller.connect()

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(thread_cls.call_count, 2, "connect() should create worker threads only once")
        self.assertEqual(thread_1.start.call_count, 1)
        self.assertEqual(thread_2.start.call_count, 1)
        self.assertEqual(serial_cls.call_count, 1)


if __name__ == "__main__":
    unittest.main()
