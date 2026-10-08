"""
TASCAM CD-400U RS-232C Controller
Handles communication with TASCAM CD-400U/CD-400UDAB via RS-232
"""

import logging
import queue
import threading
import time
from typing import Any, Dict, Optional

import serial

logger = logging.getLogger(__name__)

DEFAULT_PORT = '/dev/serial/by-id/usb-FTDI_USB_Serial_Converter_FTEM3Y6M-if00-port0'


def _default_status() -> Dict[str, Any]:
    return {
        'mecha_status': 'unknown',
        'track_number': 0,  # Currently playing/selected track (D5)
        'current_track': 0,  # Current track info from D7
        'total_tracks': 0,  # Total tracks on disc (DD)
        'time_elapsed': '00:00',  # Current track time
        'time_remaining': '00:00',
        'total_time': '00:00',  # Total disc time (DD)
        'media_present': False,
        'media_type': 'unknown',
        'play_mode': 'continuous',
        'repeat_mode': False,
        'resume_mode': False,
        'incremental_play': False,
        'remote_local_mode': 'unknown',
        'device': 'CD',
        'device_name': 'CD',
        'is_tuner': False,
        'error_status': None,  # Structured error info from F8
        'caution_status': None  # Structured caution info from F9
    }


class TascamController:
    """Controller for TASCAM CD-400U via RS-232C protocol.

    One background thread owns the serial port. Every pass it applies every
    complete reply the deck has sent, then sends at most one command: a
    queued operator command if there is one, otherwise the next status query.
    Commands are spaced CMD_INTERVAL apart. If the port can't be opened (USB
    adapter missing) the thread keeps retrying; if the deck stops answering
    (powered off) the port stays open and `online` goes False until it
    answers again.
    """

    # Command codes
    CMD_INFORMATION_REQUEST = '0F'
    CMD_STOP = '10'
    CMD_PLAY = '12'
    CMD_READY = '14'
    CMD_SEARCH = '16'
    CMD_EJECT = '18'
    CMD_TRACK_SKIP = '1A'
    CMD_DIRECT_TRACK_SEARCH = '23'
    CMD_RESUME_PLAY_SELECT = '34'
    CMD_RESUME_PLAY_SENSE = '35'
    CMD_REPEAT_SELECT = '37'
    CMD_REPEAT_SENSE = '38'
    CMD_INCR_PLAY_SELECT = '3A'
    CMD_INCR_PLAY_SENSE = '3B'
    CMD_CLEAR = '4A'  # Clear/dismiss message (like NO button)
    CMD_REMOTE_LOCAL_SELECT = '4C'
    CMD_REMOTE_LOCAL_SENSE = '4D'
    CMD_PLAY_MODE_SELECT = '4E'
    CMD_PLAY_MODE_SENSE = '4F'
    CMD_MECHA_STATUS_SENSE = '50'
    CMD_TRACK_NO_SENSE = '55'
    CMD_MEDIA_STATUS_SENSE = '56'
    CMD_CURRENT_TRACK_INFO_SENSE = '57'
    CMD_CURRENT_TRACK_TIME_SENSE = '58'
    CMD_TOTAL_TRACK_TIME_SENSE = '5D'  # Get total tracks and total time
    CMD_ERROR_SENSE = '78'
    CMD_CAUTION_SENSE = '79'

    # Vendor commands (7F prefix)
    CMD_DEVICE_SELECT = '7F01'  # Device/source selection
    CMD_ENTER = '7F7049'  # ENTER button (menu navigation/confirm)
    CMD_BACK = '7F704A'  # BACK button (menu navigation)

    # Return command codes
    RET_INFORMATION = '8F'
    RET_RESUME_PLAY = 'B5'  # Resume mode return
    RET_REPEAT = 'B8'  # Repeat mode return
    RET_INCR_PLAY = 'BB'  # Incremental play return
    RET_REMOTE_LOCAL = 'CD'  # Remote/local mode return
    RET_PLAY_MODE = 'CF'
    RET_MECHA_STATUS = 'D0'
    RET_TRACK_NO = 'D5'
    RET_MEDIA_STATUS = 'D6'
    RET_CURRENT_TRACK_INFO = 'D7'
    RET_CURRENT_TRACK_TIME = 'D8'
    RET_TOTAL_TRACK_TIME = 'DD'  # Return for total tracks/time query
    RET_ERROR_SENSE_REQUEST = 'F0'
    RET_CAUTION_SENSE_REQUEST = 'F1'
    RET_ILLEGAL_STATUS = 'F2'
    RET_POWER_ON_STATUS = 'F4'
    RET_CHANGE_STATUS = 'F6'
    RET_ERROR_SENSE = 'F8'
    RET_CAUTION_SENSE = 'F9'
    RET_VENDOR = 'FF'  # Vendor command return (check category byte)

    # Machine ID
    MACHINE_ID = '0'

    # Timing constants (in seconds)
    CMD_INTERVAL = 0.1  # 100ms minimum between commands
    OFFLINE_AFTER = 3.0  # no reply for this long => deck is off / unplugged
    REOPEN_INTERVAL = 5.0  # retry period while the serial port can't be opened

    # Allowed baud rates per TASCAM RS-232C spec
    VALID_BAUDRATES = [4800, 9600, 19200, 38400, 57600]

    # Status queries. Every rotation sends the fast ones plus the next slow
    # one (0.5 s per rotation): elapsed time is read every 0.2-0.3 s,
    # transport and track every 0.5 s, each slow item every ~4.5 s.
    POLL_FAST = [
        (CMD_MECHA_STATUS_SENSE, ''),
        (CMD_CURRENT_TRACK_TIME_SENSE, '00'),
        (CMD_TRACK_NO_SENSE, ''),
        (CMD_CURRENT_TRACK_TIME_SENSE, '00'),
    ]
    POLL_SLOW = [
        (CMD_MEDIA_STATUS_SENSE, ''),
        (CMD_TOTAL_TRACK_TIME_SENSE, ''),
        (CMD_DEVICE_SELECT, 'FF'),
        (CMD_PLAY_MODE_SENSE, ''),
        (CMD_CURRENT_TRACK_INFO_SENSE, ''),
        (CMD_REPEAT_SENSE, ''),
        (CMD_RESUME_PLAY_SENSE, ''),
        (CMD_INCR_PLAY_SENSE, ''),
        (CMD_REMOTE_LOCAL_SENSE, ''),
    ]
    # Re-read right after the deck announces a change (F6), e.g. a disc
    # going in, a track ending, or a button pressed on the front panel.
    POLL_ON_CHANGE = [
        (CMD_MECHA_STATUS_SENSE, ''),
        (CMD_TRACK_NO_SENSE, ''),
        (CMD_CURRENT_TRACK_TIME_SENSE, '00'),
        (CMD_MEDIA_STATUS_SENSE, ''),
        (CMD_TOTAL_TRACK_TIME_SENSE, ''),
        (CMD_DEVICE_SELECT, 'FF'),
    ]

    def __init__(self, port: str = DEFAULT_PORT, baudrate: int = 9600):
        """
        Initialize TASCAM controller

        Args:
            port: Serial port path (persistent by-id path recommended)
            baudrate: Baud rate (4800, 9600, 19200, 38400, 57600)

        Raises:
            ValueError: If baudrate is not in the allowed set
        """
        if baudrate not in self.VALID_BAUDRATES:
            raise ValueError(f"Invalid baudrate {baudrate}. Must be one of {self.VALID_BAUDRATES}")

        self.port = port
        self.baudrate = baudrate
        self.serial: Optional[serial.Serial] = None
        self.current_status = _default_status()
        self.last_reply = 0.0  # monotonic time of the last reply from the deck

        self._lock = threading.Lock()  # guards current_status
        self._commands: queue.Queue = queue.Queue()  # operator commands, sent before polls
        self._poll: list = []  # rest of the current poll rotation
        self._slow_index = 0
        self._last_send = 0.0
        self._last_open_attempt = float('-inf')
        self._open_error_logged = False
        self._was_online = False
        self._buffer = bytearray()
        self._thread: Optional[threading.Thread] = None
        self.running = False

    # --- Connection state ---

    @property
    def connected(self) -> bool:
        """The serial port is open. The deck itself may still be off."""
        port = self.serial
        return port is not None and port.is_open

    @property
    def online(self) -> bool:
        """The deck has answered within the last OFFLINE_AFTER seconds."""
        return self.connected and time.monotonic() - self.last_reply < self.OFFLINE_AFTER

    def start(self):
        """Start the I/O thread. It opens the port (retrying until it can)
        and keeps polling the deck until shutdown() is called."""
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._io_loop, daemon=True, name='tascam-io')
        self._thread.start()

    def shutdown(self):
        """Stop the I/O thread and close the port."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self._close_port()
        logger.info("Stopped")

    # --- Serial I/O ---

    def _io_loop(self):
        while self.running:
            if not self.connected and not self._open_port():
                time.sleep(0.2)
                continue
            try:
                self._read_replies()
                self._track_online()
                self._send_next()
            except (serial.SerialException, OSError) as e:
                logger.warning(f"Serial port error, reopening: {e}")
                self._close_port()
            time.sleep(0.01)

    def _open_port(self) -> bool:
        now = time.monotonic()
        if now - self._last_open_attempt < self.REOPEN_INTERVAL:
            return False
        self._last_open_attempt = now
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0,
                write_timeout=1.0,
                rtscts=False  # No real flow control - pins 7&8 are shorted internally
            )
        except (serial.SerialException, OSError, ValueError) as e:
            self.serial = None
            log = logger.debug if self._open_error_logged else logger.warning
            log(f"Cannot open {self.port}: {e} (retrying every {self.REOPEN_INTERVAL:.0f}s)")
            self._open_error_logged = True
            return False
        self._open_error_logged = False
        self._buffer.clear()
        self._poll = []
        logger.info(f"Opened {self.port} at {self.baudrate} baud")
        return True

    def _close_port(self):
        if self.serial is not None:
            try:
                self.serial.close()
            except Exception:
                pass
        self.serial = None
        self._track_online()

    def _read_replies(self):
        """Apply every complete reply waiting on the port."""
        waiting = self.serial.in_waiting
        if waiting:
            self._buffer.extend(self.serial.read(waiting))
        while True:
            cr = self._buffer.find(b'\r')
            if cr < 0:
                break
            frame = bytes(self._buffer[:cr])
            del self._buffer[:cr + 1]
            reply = self._parse_frame(frame)
            if reply is None:
                continue
            self.last_reply = time.monotonic()
            try:
                self._handle_response(*reply)
            except (ValueError, IndexError) as e:
                logger.debug(f"Ignoring malformed reply {frame!r}: {e}")
        if len(self._buffer) > 4096:  # line noise with no CR; don't grow forever
            self._buffer.clear()

    @staticmethod
    def _parse_frame(frame: bytes) -> Optional[tuple]:
        """[LF][ID][CMD x2][DATA...] (CR already stripped) -> (cmd, data)."""
        lf = frame.rfind(b'\n')
        if lf < 0:
            return None
        msg_str = frame[lf + 1:].decode('ascii', errors='ignore')
        if len(msg_str) < 3:
            return None
        return msg_str[1:3], msg_str[3:]

    def _track_online(self):
        online = self.online
        if online and not self._was_online:
            logger.info("Deck is responding")
            # Remote + front panel enabled ('01' = best for church use).
            # Re-applied every time the deck comes back (power cycle, cable).
            self._commands.put((self.CMD_REMOTE_LOCAL_SELECT, '01'))
            self._poll = self.POLL_FAST + self.POLL_SLOW  # full refresh
        elif not online and self._was_online:
            if self.running:
                logger.warning("Deck stopped responding")
            # Don't fire stale button presses at the deck when it returns.
            self._clear_commands()
            with self._lock:
                self.current_status = _default_status()
        self._was_online = online

    def _clear_commands(self):
        while True:
            try:
                self._commands.get_nowait()
            except queue.Empty:
                return

    def _send_next(self):
        if time.monotonic() - self._last_send < self.CMD_INTERVAL:
            return
        try:
            command, data = self._commands.get_nowait()
        except queue.Empty:
            if not self._poll:
                self._poll = self.POLL_FAST + [self.POLL_SLOW[self._slow_index]]
                self._slow_index = (self._slow_index + 1) % len(self.POLL_SLOW)
            command, data = self._poll.pop(0)
        self.serial.write(self._build_command(command, data))
        self._last_send = time.monotonic()
        logger.debug(f"Sent command: {command} {data}")

    def _build_command(self, command: str, data: str = '') -> bytes:
        """
        Build a command in TASCAM protocol format

        Format: [LF][ID][COMMAND][DATA][CR]
        Vendor commands (7F/FF) carry their category in the command string.
        """
        cmd_str = f"\n{self.MACHINE_ID}{command}{data}\r"
        return cmd_str.encode('ascii')

    def send_command(self, command: str, data: str = ''):
        """Queue a command; it goes out ahead of any pending status polls."""
        self._commands.put((command, data))

    def _handle_response(self, command: str, data: str):
        """Handle response from device"""
        with self._lock:
            self._apply_response(command, data)

    def _apply_response(self, command: str, data: str):
        status = self.current_status

        if command == self.RET_MECHA_STATUS:
            # Parse mecha status
            status_map = {
                '00': 'no_media',
                '01': 'ejecting',
                '10': 'stop',
                '11': 'play',
                '12': 'ready',
                '28': 'search_forward',
                '29': 'search_backward',
                'FF': 'other'
            }
            status['mecha_status'] = status_map.get(data[:2], 'unknown')

        elif command == self.RET_TRACK_NO:
            # Parse track number (format: tens, ones, thousands, hundreds)
            if len(data) >= 4:
                tens = int(data[0])
                ones = int(data[1])
                thousands = int(data[2])
                hundreds = int(data[3])
                track_num = thousands * 1000 + hundreds * 100 + tens * 10 + ones
                status['track_number'] = track_num

        elif command == self.RET_CURRENT_TRACK_TIME:
            # Parse time (format: type, min_tens, min_ones, min_thousands, min_hundreds, sec_tens, sec_ones, ...)
            if len(data) >= 10:
                min_tens = int(data[2])
                min_ones = int(data[3])
                min_thousands = int(data[4])
                min_hundreds = int(data[5])
                sec_tens = int(data[6])
                sec_ones = int(data[7])
                # Calculate minutes from all 4 digits (supports >99 minutes)
                minutes = (min_thousands * 1000) + (min_hundreds * 100) + (min_tens * 10) + min_ones
                seconds = sec_tens * 10 + sec_ones
                status['time_elapsed'] = f"{minutes:02d}:{seconds:02d}"

        elif command == self.RET_MEDIA_STATUS:
            # Parse media status (4 bytes: media present, media type)
            if len(data) >= 4:
                status['media_present'] = (data[:2] == '01')
                media_type_code = data[2:4]
                media_type_map = {
                    '00': 'CD-DA/Audio',
                    '10': 'CD-ROM/Data'
                }
                status['media_type'] = media_type_map.get(media_type_code, 'Unknown')

        elif command == self.RET_CURRENT_TRACK_INFO:
            # D7: CURRENT TRACK INFORMATION RETURN
            # Per PDF spec: Returns current track/preset info (not total tracks)
            # For CD/USB/SD: current track number
            # For tuner: current preset/frequency info
            if len(data) >= 4:
                tens = int(data[0])
                ones = int(data[1])
                thousands = int(data[2])
                hundreds = int(data[3])
                current_track = thousands * 1000 + hundreds * 100 + tens * 10 + ones
                status['current_track'] = current_track

        elif command == self.RET_PLAY_MODE:
            # Parse play mode (2 bytes)
            if len(data) >= 2:
                mode_map = {
                    '00': 'continuous',
                    '01': 'single',
                    '06': 'random'
                }
                status['play_mode'] = mode_map.get(data[:2], 'continuous')

        elif command == self.RET_TOTAL_TRACK_TIME:
            # Parse total tracks and total time (12 bytes)
            if len(data) >= 12:
                # Total tracks (bytes 0-3: tens, ones, thousands, hundreds)
                tens = int(data[0])
                ones = int(data[1])
                thousands = int(data[2])
                hundreds = int(data[3])
                total_tracks = thousands * 1000 + hundreds * 100 + tens * 10 + ones
                status['total_tracks'] = total_tracks

                # Total time (bytes 4-9: not supported for Data-CD/USB/SD)
                if data[4:10] != '000000':
                    min_tens = int(data[4])
                    min_ones = int(data[5])
                    min_thousands = int(data[6])
                    min_hundreds = int(data[7])
                    sec_tens = int(data[8])
                    sec_ones = int(data[9])
                    # Calculate minutes from all 4 digits (supports >99 minutes)
                    minutes = (min_thousands * 1000) + (min_hundreds * 100) + (min_tens * 10) + min_ones
                    seconds = sec_tens * 10 + sec_ones
                    status['total_time'] = f"{minutes:02d}:{seconds:02d}"

        elif command == self.RET_VENDOR:
            # FF: Vendor command return - check category byte
            if len(data) >= 2:
                category = data[:2]
                if category == '01':  # DEVICE SELECT RETURN
                    # Data7 = device kind, Data8 = device index
                    if len(data) >= 8:
                        device_kind = data[6:8]
                        # Decode device kind per PDF spec (CD-400U)
                        device_map = {
                            '00': ('sd', 'SD Card'),
                            '10': ('usb', 'USB'),
                            '11': ('cd', 'CD'),
                            '20': ('bluetooth', 'Bluetooth'),
                            '30': ('fm', 'FM Radio'),  # CD-400U
                            '31': ('am', 'AM Radio'),  # CD-400U
                            '40': ('aux', 'AUX Input')
                        }
                        if device_kind in device_map:
                            device_code, device_name = device_map[device_kind]
                            status['device'] = device_code
                            status['device_name'] = device_name
                            status['is_tuner'] = device_code in ['fm', 'am']

        elif command == self.RET_RESUME_PLAY:
            # B5: Resume mode return
            if len(data) >= 2:
                status['resume_mode'] = (data[:2] == '01')

        elif command == self.RET_REPEAT:
            # B8: Repeat mode return
            if len(data) >= 2:
                status['repeat_mode'] = (data[:2] == '01')

        elif command == self.RET_INCR_PLAY:
            # BB: Incremental play return
            if len(data) >= 2:
                status['incremental_play'] = (data[:2] == '01')

        elif command == self.RET_REMOTE_LOCAL:
            # CD: Remote/local mode return
            if len(data) >= 2:
                mode_map = {
                    '00': 'remote_only',
                    '01': 'remote_and_local'
                }
                status['remote_local_mode'] = mode_map.get(data[:2], 'unknown')

        elif command == self.RET_ERROR_SENSE:
            # F8: Error status return - parse error bits
            if len(data) >= 2:
                error_byte = int(data[:2], 16)
                errors = []
                if error_byte & 0x01: errors.append('focus_error')
                if error_byte & 0x02: errors.append('tracking_error')
                if error_byte & 0x04: errors.append('spindle_error')
                if error_byte & 0x08: errors.append('sled_error')
                if error_byte & 0x10: errors.append('tray_error')
                if error_byte & 0x20: errors.append('no_disc')
                if error_byte & 0x40: errors.append('cannot_play')
                if error_byte & 0x80: errors.append('other_error')

                status['error_status'] = {
                    'raw': error_byte,
                    'errors': errors,
                    'has_error': len(errors) > 0
                }
                if errors:
                    logger.warning(f"Device errors: {', '.join(errors)}")

        elif command == self.RET_CAUTION_SENSE:
            # F9: Caution status return - parse caution bits
            if len(data) >= 2:
                caution_byte = int(data[:2], 16)
                cautions = []
                if caution_byte & 0x01: cautions.append('unsupported_disc')
                if caution_byte & 0x02: cautions.append('dirty_disc')
                if caution_byte & 0x04: cautions.append('no_audio')
                if caution_byte & 0x08: cautions.append('temperature_high')
                if caution_byte & 0x10: cautions.append('copyright_protected')

                status['caution_status'] = {
                    'raw': caution_byte,
                    'cautions': cautions,
                    'has_caution': len(cautions) > 0
                }
                if cautions:
                    logger.info(f"Device cautions: {', '.join(cautions)}")

        elif command == self.RET_CHANGE_STATUS:
            # F6: Status changed - re-read the essentials right away
            logger.debug("Status changed notification received - forcing update")
            self._poll = self.POLL_ON_CHANGE + self._poll

        elif command == self.RET_ERROR_SENSE_REQUEST:
            # F0: Error occurred - query error details
            self.send_command(self.CMD_ERROR_SENSE)

        elif command == self.RET_CAUTION_SENSE_REQUEST:
            # F1: Caution state - query caution details
            self.send_command(self.CMD_CAUTION_SENSE)

        elif command == self.RET_POWER_ON_STATUS:
            # F4: Deck just powered on - put it back in remote mode
            self.send_command(self.CMD_REMOTE_LOCAL_SELECT, '01')

        elif command == self.RET_ILLEGAL_STATUS:
            logger.warning("Illegal command/status received")

    # Transport control methods
    def play(self):
        """Start playback"""
        self.send_command(self.CMD_PLAY)

    def stop(self):
        """Stop playback"""
        self.send_command(self.CMD_STOP)

    def eject(self):
        """Eject CD"""
        self.send_command(self.CMD_EJECT)

    def next_track(self):
        """Skip to next track"""
        self.send_command(self.CMD_TRACK_SKIP, '00')

    def previous_track(self):
        """Skip to previous track"""
        self.send_command(self.CMD_TRACK_SKIP, '01')

    def search_forward(self, high_speed: bool = False):
        """Search forward"""
        data = '10' if high_speed else '00'
        self.send_command(self.CMD_SEARCH, data)

    def search_reverse(self, high_speed: bool = False):
        """Search backward"""
        data = '11' if high_speed else '01'
        self.send_command(self.CMD_SEARCH, data)

    def goto_track(self, track_number: int):
        """
        Go to specific track

        Args:
            track_number: Track number (1-999)
        """
        if not 1 <= track_number <= 999:
            logger.error(f"Invalid track number: {track_number}")
            return

        # Format: tens, ones, thousands, hundreds
        thousands = (track_number // 1000) % 10
        hundreds = (track_number // 100) % 10
        tens = (track_number // 10) % 10
        ones = track_number % 10

        data = f"{tens}{ones}{thousands}{hundreds}"
        self.send_command(self.CMD_DIRECT_TRACK_SEARCH, data)

    def set_play_mode(self, mode: str):
        """
        Set playback mode

        Args:
            mode: 'continuous', 'single', or 'random'
        """
        mode_map = {
            'continuous': '00',
            'single': '01',
            'random': '06'
        }

        if mode in mode_map:
            self.send_command(self.CMD_PLAY_MODE_SELECT, mode_map[mode])
            with self._lock:
                self.current_status['play_mode'] = mode
        else:
            logger.error(f"Invalid play mode: {mode}")

    def set_repeat(self, enabled: bool):
        """Enable/disable repeat mode"""
        data = '01' if enabled else '00'
        self.send_command(self.CMD_REPEAT_SELECT, data)
        with self._lock:
            self.current_status['repeat_mode'] = enabled

    def pause(self):
        """Pause/Ready mode (playback standby)"""
        self.send_command(self.CMD_READY, '01')

    def resume(self):
        """Resume from pause (exit ready mode by playing)"""
        # READY '00' is invalid per spec, use PLAY to exit ready mode
        self.send_command(self.CMD_PLAY)

    def set_resume_mode(self, enabled: bool):
        """Enable/disable resume play mode"""
        data = '01' if enabled else '00'
        self.send_command(self.CMD_RESUME_PLAY_SELECT, data)
        with self._lock:
            self.current_status['resume_mode'] = enabled

    def set_incremental_play(self, enabled: bool):
        """Enable/disable incremental playback"""
        data = '01' if enabled else '00'
        self.send_command(self.CMD_INCR_PLAY_SELECT, data)

    def search_start(self, forward: bool = True, high_speed: bool = False):
        """Start searching forward or backward"""
        if forward:
            data = '10' if high_speed else '00'
        else:
            data = '11' if high_speed else '01'
        self.send_command(self.CMD_SEARCH, data)

    def search_stop(self):
        """Stop searching (by issuing play command)"""
        self.send_command(self.CMD_PLAY)

    def switch_device(self, device: str):
        """
        Switch input source/device (CD-400U)

        Args:
            device: One of 'cd', 'usb', 'sd', 'bluetooth', 'fm', 'am', 'aux'
        """
        device_map = {
            'sd': '00',
            'usb': '10',
            'cd': '11',
            'bluetooth': '20',
            'fm': '30',
            'am': '31',
            'aux': '40'
        }
        device_names = {
            'sd': 'SD Card',
            'usb': 'USB',
            'cd': 'CD',
            'bluetooth': 'Bluetooth',
            'fm': 'FM Radio',
            'am': 'AM Radio',
            'aux': 'AUX Input'
        }

        device_lower = device.lower()
        if device_lower in device_map:
            # Vendor command format: 7F01 (command) + device code (data)
            # Creates: LF 0 7F01 <device_code> CR
            self.send_command(self.CMD_DEVICE_SELECT, device_map[device_lower])
            with self._lock:
                self.current_status['device'] = device_lower
                self.current_status['device_name'] = device_names[device_lower]
                # Mark if device is a tuner/radio
                self.current_status['is_tuner'] = device_lower in ['fm', 'am']
        else:
            logger.error(f"Invalid device: {device}")

    # Tuner controls (for FM/AM radio)
    def tuner_frequency_up(self):
        """Tune to next frequency/station (for radio sources)"""
        # Uses track skip command - works as frequency up for tuners
        self.send_command(self.CMD_TRACK_SKIP, '00')

    def tuner_frequency_down(self):
        """Tune to previous frequency/station (for radio sources)"""
        # Uses track skip command - works as frequency down for tuners
        self.send_command(self.CMD_TRACK_SKIP, '01')

    def tuner_seek_up(self):
        """Auto-seek next station (for radio sources)"""
        # Uses search command for auto-seek
        self.send_command(self.CMD_SEARCH, '00')

    def tuner_seek_down(self):
        """Auto-seek previous station (for radio sources)"""
        # Uses search command for auto-seek
        self.send_command(self.CMD_SEARCH, '01')

    def tuner_preset(self, preset_number: int):
        """
        Select tuner preset (for radio sources)

        Args:
            preset_number: Preset number (1-20 per spec)
        """
        if not 1 <= preset_number <= 20:
            logger.error(f"Invalid preset number: {preset_number} (valid range: 1-20)")
            return

        # Uses direct track search command for preset selection
        # Format: tens, ones, thousands, hundreds
        thousands = (preset_number // 1000) % 10
        hundreds = (preset_number // 100) % 10
        tens = (preset_number // 10) % 10
        ones = preset_number % 10

        data = f"{tens}{ones}{thousands}{hundreds}"
        self.send_command(self.CMD_DIRECT_TRACK_SEARCH, data)

    # Additional utility commands
    def clear(self):
        """Clear/dismiss message or dialog (like NO button)"""
        self.send_command(self.CMD_CLEAR)

    def enter(self):
        """Send ENTER command (menu navigation/confirmation)"""
        self.send_command(self.CMD_ENTER, '01')

    def back(self):
        """Send BACK command (menu navigation)"""
        self.send_command(self.CMD_BACK, '01')

    def get_total_info(self):
        """Request total tracks and total time from disc/media"""
        self.send_command(self.CMD_TOTAL_TRACK_TIME_SENSE)

    def get_status(self) -> Dict[str, Any]:
        """Current device status, plus whether the port is open and the deck answering."""
        with self._lock:
            status = dict(self.current_status)
        status['port_open'] = self.connected
        status['online'] = self.online
        return status
