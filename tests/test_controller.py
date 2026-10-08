import time
import unittest
from unittest.mock import patch

import serial

from tascam_controller import TascamController


class FakeSerial:
    """In-memory stand-in for serial.Serial."""

    def __init__(self, **kwargs):
        self.is_open = True
        self.incoming = bytearray()
        self.written = []

    @property
    def in_waiting(self):
        return len(self.incoming)

    def read(self, n):
        data = bytes(self.incoming[:n])
        del self.incoming[:n]
        return data

    def write(self, data):
        self.written.append(data)
        return len(data)

    def close(self):
        self.is_open = False

    def reply(self, *frames):
        for frame in frames:
            self.incoming.extend(f"\n0{frame}\r".encode('ascii'))


class ControllerTestCase(unittest.TestCase):
    def setUp(self):
        self.port = FakeSerial()
        patcher = patch('tascam_controller.serial.Serial', return_value=self.port)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ctrl = TascamController(port='/dev/fake', baudrate=9600)
        self.assertTrue(self.ctrl._open_port())

    def send_next(self):
        """Send whatever goes out next, ignoring the 100 ms spacing."""
        self.ctrl._last_send = 0.0
        before = len(self.port.written)
        self.ctrl._send_next()
        return self.port.written[before] if len(self.port.written) > before else None


class ReplyHandlingTests(ControllerTestCase):
    def test_every_waiting_reply_is_applied_in_one_pass(self):
        # Regression: the old poll loop parsed one reply per ~0.35 s cycle
        # while asking for three or more, so replies queued up without limit
        # and the display showed older and older state.
        self.port.reply('D011', 'D50700', 'D80003004200', 'DD120047003200')
        self.ctrl._read_replies()

        status = self.ctrl.get_status()
        self.assertEqual(status['mecha_status'], 'play')
        self.assertEqual(status['track_number'], 7)
        self.assertEqual(status['time_elapsed'], '03:42')
        self.assertEqual(status['total_tracks'], 12)
        self.assertEqual(self.port.in_waiting, 0)

    def test_malformed_reply_is_skipped(self):
        self.port.reply('D5XX00', 'D011')
        self.ctrl._read_replies()
        self.assertEqual(self.ctrl.get_status()['mecha_status'], 'play')

    def test_partial_reply_waits_for_the_rest(self):
        self.port.incoming.extend(b'\n0D0')
        self.ctrl._read_replies()
        self.assertEqual(self.ctrl.get_status()['mecha_status'], 'unknown')
        self.port.incoming.extend(b'12\r')
        self.ctrl._read_replies()
        self.assertEqual(self.ctrl.get_status()['mecha_status'], 'ready')

    def test_noise_before_a_frame_is_ignored(self):
        self.port.incoming.extend(b'\x00\xff\n0D010\r')
        self.ctrl._read_replies()
        self.assertEqual(self.ctrl.get_status()['mecha_status'], 'stop')


class SendingTests(ControllerTestCase):
    def test_operator_command_goes_before_polls(self):
        self.ctrl.play()
        self.assertEqual(self.send_next(), b'\n012\r')
        self.assertEqual(self.send_next(), b'\n050\r')  # then polling resumes

    def test_commands_are_spaced_at_least_100ms(self):
        self.ctrl._send_next()
        self.ctrl.play()
        self.ctrl._send_next()  # immediately after: must wait
        self.assertEqual(len(self.port.written), 1)
        time.sleep(TascamController.CMD_INTERVAL)
        self.ctrl._send_next()
        self.assertEqual(self.port.written[-1], b'\n012\r')

    def test_polls_cover_fast_and_slow_queries(self):
        rotation = len(TascamController.POLL_FAST) + 1
        sent = {self.send_next() for _ in range(rotation * len(TascamController.POLL_SLOW))}
        for command, data in TascamController.POLL_FAST + TascamController.POLL_SLOW:
            self.assertIn(f"\n0{command}{data}\r".encode(), sent)

    def test_change_status_rereads_right_away(self):
        self.port.reply('F600')
        self.ctrl._read_replies()
        self.assertEqual(self.send_next(), b'\n050\r')
        self.assertEqual(self.send_next(), b'\n055\r')

    def test_track_number_encoding(self):
        self.ctrl.goto_track(123)
        self.assertEqual(self.send_next(), b'\n0232301\r')


class OnlineTests(ControllerTestCase):
    def test_first_reply_puts_deck_in_remote_mode(self):
        self.assertFalse(self.ctrl.online)
        self.port.reply('D010')
        self.ctrl._read_replies()
        self.ctrl._track_online()
        self.assertTrue(self.ctrl.online)
        self.assertEqual(self.send_next(), b'\n04C01\r')

    def test_silence_goes_offline_and_drops_stale_commands(self):
        self.port.reply('D011')
        self.ctrl._read_replies()
        self.ctrl._track_online()
        self.ctrl._clear_commands()
        self.ctrl.play()

        self.ctrl.last_reply = time.monotonic() - TascamController.OFFLINE_AFTER - 0.1
        self.ctrl._track_online()

        status = self.ctrl.get_status()
        self.assertFalse(status['online'])
        self.assertTrue(status['port_open'])
        self.assertEqual(status['mecha_status'], 'unknown')
        self.assertTrue(self.ctrl._commands.empty())

    def test_missing_port_is_retried_without_crashing(self):
        ctrl = TascamController(port='/dev/missing', baudrate=9600)
        with patch('tascam_controller.serial.Serial',
                   side_effect=serial.SerialException('no such port')) as opener:
            self.assertFalse(ctrl._open_port())
            self.assertFalse(ctrl._open_port())  # too soon to retry
            self.assertEqual(opener.call_count, 1)
        status = ctrl.get_status()
        self.assertFalse(status['port_open'])
        self.assertFalse(status['online'])

    def test_rejects_invalid_baudrate(self):
        with self.assertRaises(ValueError):
            TascamController(port='/dev/null', baudrate=115200)


if __name__ == '__main__':
    unittest.main()
