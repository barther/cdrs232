"""Controller against the simulated deck over a real pseudo-terminal."""

import time
import unittest

from tascam_controller import TascamController

try:
    from tascam_sim import TascamSimulator
except ImportError:  # pty is POSIX-only
    TascamSimulator = None


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def seconds(mmss):
    m, s = mmss.split(':')
    return int(m) * 60 + int(s)


@unittest.skipIf(TascamSimulator is None, 'needs a POSIX pty')
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.sim = TascamSimulator()
        self.ctrl = TascamController(port=self.sim.start(), baudrate=9600)
        self.ctrl.start()
        self.addCleanup(self.sim.stop)
        self.addCleanup(self.ctrl.shutdown)
        self.assertTrue(wait_for(lambda: self.ctrl.online), 'deck never came online')

    def status(self):
        return self.ctrl.get_status()

    def test_display_keeps_up_with_the_deck(self):
        self.ctrl.play()
        self.assertTrue(wait_for(lambda: self.status()['mecha_status'] == 'play', 1.0))
        for _ in range(10):
            time.sleep(0.37)
            behind = int(self.sim.position) - seconds(self.status()['time_elapsed'])
            self.assertLessEqual(behind, 1)  # whole seconds, as displayed

    def test_track_select_and_disc_info(self):
        self.assertTrue(wait_for(lambda: self.status()['total_tracks'] == len(self.sim.tracks)))
        self.ctrl.goto_track(5)
        self.assertTrue(wait_for(lambda: self.status()['track_number'] == 5, 1.0))

    def test_deck_power_cycle(self):
        self.sim.responding = False
        self.assertTrue(wait_for(lambda: not self.ctrl.online))
        self.sim.remote = '00'
        self.sim.responding = True
        self.assertTrue(wait_for(lambda: self.ctrl.online))
        self.assertTrue(wait_for(lambda: self.sim.remote == '01', 1.0))


if __name__ == '__main__':
    unittest.main()
