"""
Fake TASCAM CD-400U on a pseudo-terminal, for running and testing the web
controller without the real deck.

    python app.py --sim          # web UI against a simulated deck
    python tascam_sim.py         # just the deck; prints the port to point at

Replies use the same field layouts tascam_controller.py parses. Time runs
while "playing", tracks advance at the end, and transport/track/mode/source
commands change the simulated state.
"""

import os
import pty
import select
import threading
import time
import tty

# Track lengths in seconds for the simulated disc.
DEFAULT_TRACKS = (185, 243, 201, 317, 158, 276, 222, 199, 264, 141, 305, 233)

DEVICE_CODES = {'00', '10', '11', '20', '30', '31', '40'}


def _track_digits(n: int) -> str:
    """Track number as the deck sends it: tens, ones, thousands, hundreds."""
    return f"{(n // 10) % 10}{n % 10}{(n // 1000) % 10}{(n // 100) % 10}"


def _time_digits(seconds: int) -> str:
    """Minutes (tens, ones, thousands, hundreds) then seconds (tens, ones)."""
    m, s = divmod(int(seconds), 60)
    return f"{(m // 10) % 10}{m % 10}{(m // 1000) % 10}{(m // 100) % 10}{s // 10}{s % 10}"


class TascamSimulator:
    def __init__(self, tracks=DEFAULT_TRACKS):
        self.tracks = list(tracks)
        self.mecha = '10'          # 00 no media, 10 stop, 11 play, 12 ready, 28/29 search
        self.track = 1
        self.position = 0.0        # seconds into the current track
        self.play_mode = '00'
        self.device = '11'
        self.repeat = False
        self.resume = False
        self.incr = False
        self.remote = '01'
        self.responding = True     # set False to simulate a powered-off deck
        self._search_speed = 0
        self._last_tick = time.monotonic()
        self._reload_at = None
        self._lock = threading.Lock()
        self._running = False

        self._master, self._slave = pty.openpty()
        tty.setraw(self._slave)
        self.port = os.ttyname(self._slave)

    # -- lifecycle --------------------------------------------------------

    def start(self):
        self._running = True
        threading.Thread(target=self._serve, daemon=True, name='tascam-sim').start()
        return self.port

    def stop(self):
        self._running = False

    # -- time model -------------------------------------------------------

    def _tick(self):
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now
        if self._reload_at and now >= self._reload_at:
            self._reload_at = None
            self.mecha, self.track, self.position = '10', 1, 0.0
        if self.mecha == '11':
            self.position += dt
        elif self.mecha in ('28', '29'):
            self.position = max(0.0, self.position + dt * self._search_speed)
        if self.mecha in ('11', '28') and self.position >= self.tracks[self.track - 1]:
            if self.track < len(self.tracks) and self.play_mode != '01':
                self.track += 1
                self.position = 0.0
                self._push('F6', '03')
            else:
                self.mecha, self.position = '10', 0.0
                self._push('F6', '00')

    # -- serial plumbing --------------------------------------------------

    def _push(self, cmd: str, data: str = ''):
        if self.responding:
            os.write(self._master, f"\n0{cmd}{data}\r".encode('ascii'))

    def _serve(self):
        buf = b''
        while self._running:
            ready, _, _ = select.select([self._master], [], [], 0.05)
            with self._lock:
                self._tick()
                if not ready:
                    continue
                try:
                    buf += os.read(self._master, 1024)
                except OSError:
                    return
                while b'\r' in buf:
                    msg, buf = buf.split(b'\r', 1)
                    start = msg.rfind(b'\n')
                    if start < 0:
                        continue
                    text = msg[start + 1:].decode('ascii', errors='ignore')
                    if len(text) >= 3 and self.responding:
                        self._handle(text[1:])

    # -- protocol ---------------------------------------------------------

    def _handle(self, body: str):
        if body.startswith('7F01'):
            code = body[4:6]
            if code == 'FF':
                self._push('FF', f"010000{self.device}00")
            elif code in DEVICE_CODES:
                self.device = code
            return

        cmd, data = body[:2], body[2:]
        has_disc = self.mecha not in ('00', '01')
        total = sum(self.tracks)

        if cmd == '50':
            self._push('D0', self.mecha)
        elif cmd == '55':
            self._push('D5', _track_digits(self.track if has_disc else 0))
        elif cmd == '57':
            self._push('D7', _track_digits(self.track if has_disc else 0))
        elif cmd == '58':
            self._push('D8', '00' + _time_digits(self.position if has_disc else 0) + '00')
        elif cmd == '56':
            self._push('D6', ('01' if has_disc else '00') + '00')
        elif cmd == '5D':
            if has_disc:
                self._push('DD', _track_digits(len(self.tracks)) + _time_digits(total) + '00')
            else:
                self._push('DD', '0000' + '000000' + '00')
        elif cmd == '4F':
            self._push('CF', self.play_mode)
        elif cmd == '35':
            self._push('B5', '01' if self.resume else '00')
        elif cmd == '38':
            self._push('B8', '01' if self.repeat else '00')
        elif cmd == '3B':
            self._push('BB', '01' if self.incr else '00')
        elif cmd == '4D':
            self._push('CD', self.remote)
        elif cmd == '4C':
            self.remote = data[:2] or self.remote
        elif cmd == '4E':
            self.play_mode = data[:2] or self.play_mode
        elif cmd == '37':
            self.repeat = data[:2] == '01'
        elif cmd == '34':
            self.resume = data[:2] == '01'
        elif cmd == '3A':
            self.incr = data[:2] == '01'
        elif cmd == '12':
            if has_disc:
                self._set_mecha('11')
        elif cmd == '14':
            if has_disc and data[:2] == '01':
                self._set_mecha('12')
        elif cmd == '10':
            if has_disc:
                self.position = 0.0
                self._set_mecha('10')
        elif cmd == '18':
            self._set_mecha('00')
            self.track, self.position = 0, 0.0
            self._reload_at = time.monotonic() + 5.0
        elif cmd == '1A':
            if has_disc:
                if data[:2] == '00':
                    self.track = min(len(self.tracks), self.track + 1)
                elif self.position < 2 and self.track > 1:
                    self.track -= 1
                self.position = 0.0
                self._push('F6', '03')
        elif cmd == '23':
            if has_disc and len(data) >= 4 and data[:4].isdigit():
                d = data[:4]
                n = int(d[2]) * 1000 + int(d[3]) * 100 + int(d[0]) * 10 + int(d[1])
                if 1 <= n <= len(self.tracks):
                    self.track, self.position = n, 0.0
                    self._push('F6', '03')
        elif cmd == '16':
            if has_disc:
                fast = data[:1] == '1'
                forward = data[1:2] == '0'
                self._search_speed = (8 if fast else 4) * (1 if forward else -1)
                self._set_mecha('28' if forward else '29')
        elif cmd in ('0F', '78', '79'):
            pass
        else:
            self._push('F2')

    def _set_mecha(self, code: str):
        if code != self.mecha:
            self.mecha = code
            self._push('F6', '00')


if __name__ == '__main__':
    sim = TascamSimulator()
    print(f"Simulated CD-400U on {sim.start()}  (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
