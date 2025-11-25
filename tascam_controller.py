"""
TASCAM CD-400U RS-232C Controller
Handles communication with TASCAM CD-400U/CD-400UDAB via RS-232
"""

import serial
import time
import threading
from typing import Optional, Callable, Dict, Any
from queue import Queue
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TascamController:
    """Controller for TASCAM CD-400U via RS-232C protocol"""

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
    RESPONSE_TIMEOUT = 0.5  # 500ms for response
    STATUS_POLL_INTERVAL = 0.3  # 300ms for status polling

    # Allowed baud rates per TASCAM RS-232C spec
    VALID_BAUDRATES = [4800, 9600, 19200, 38400, 57600]

    def __init__(self, port: str = '/dev/ttyUSB0', baudrate: int = 9600):
        """
        Initialize TASCAM controller

        Args:
            port: Serial port path (e.g., '/dev/ttyUSB0')
            baudrate: Baud rate (4800, 9600, 19200, 38400, 57600)

        Raises:
            ValueError: If baudrate is not in the allowed set
        """
        if baudrate not in self.VALID_BAUDRATES:
            raise ValueError(f"Invalid baudrate {baudrate}. Must be one of {self.VALID_BAUDRATES}")

        self.port = port
        self.baudrate = baudrate
        self.serial: Optional[serial.Serial] = None
        self.connected = False

        # Command queue to ensure proper timing
        self.cmd_queue = Queue()
        self.last_cmd_time = 0

        # Connection health tracking
        self.consecutive_failures = 0
        self.max_failures_before_disconnect = 10  # ~3 seconds of failures
        self.reconnect_interval = 5.0  # Try reconnecting every 5 seconds
        self.last_reconnect_attempt = 0

        # State tracking (per PDF spec)
        self.current_status = {
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

        # Callbacks for status updates
        self.status_callbacks: list[Callable[[Dict[str, Any]], None]] = []

        # Threading
        self.cmd_thread: Optional[threading.Thread] = None
        self.poll_thread: Optional[threading.Thread] = None
        self.running = False

        # Response buffer
        self.response_buffer = bytearray()

    def connect(self) -> bool:
        """Connect to the TASCAM device"""
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1,
                rtscts=False  # No real flow control - pins 7&8 are shorted internally
            )
            self.connected = True
            self.running = True

            # Start command processing thread
            self.cmd_thread = threading.Thread(target=self._process_commands, daemon=True)
            self.cmd_thread.start()

            # Start status polling thread
            self.poll_thread = threading.Thread(target=self._poll_status, daemon=True)
            self.poll_thread.start()

            logger.info(f"Connected to TASCAM device on {self.port} at {self.baudrate} baud")

            # Set to remote control mode (enable both remote AND front panel)
            # '01' = remote + front panel enabled (best for church use)
            self._send_command_now(self.CMD_REMOTE_LOCAL_SELECT, '01')

            return True

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from the TASCAM device"""
        self.running = False

        if self.cmd_thread:
            self.cmd_thread.join(timeout=1.0)
        if self.poll_thread:
            self.poll_thread.join(timeout=1.0)

        if self.serial and self.serial.is_open:
            self.serial.close()

        self.connected = False
        self.consecutive_failures = 0
        self._reset_status()
        logger.info("Disconnected from TASCAM device")

    def _reset_status(self):
        """Reset status to default values when disconnected"""
        self.current_status = {
            'mecha_status': 'unknown',
            'track_number': 0,
            'current_track': 0,
            'total_tracks': 0,
            'time_elapsed': '00:00',
            'time_remaining': '00:00',
            'total_time': '00:00',
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
            'error_status': None,
            'caution_status': None
        }
        # Notify listeners of status reset
        self._notify_callbacks()

    def _build_command(self, command: str, data: str = '') -> bytes:
        """
        Build a command in TASCAM protocol format

        Format: [LF][ID][COMMAND][DATA][CR]
        """
        # Handle vendor commands (7F/FF with subcategory)
        if command.startswith('7F') or command.startswith('FF'):
            cmd_bytes = command
        else:
            cmd_bytes = command

        cmd_str = f"\n{self.MACHINE_ID}{cmd_bytes}{data}\r"
        return cmd_str.encode('ascii')

    def _send_command_now(self, command: str, data: str = '') -> bool:
        """Send command immediately (internal use)"""
        if not self.connected or not self.serial:
            return False

        try:
            # Ensure minimum time between commands
            elapsed = time.time() - self.last_cmd_time
            if elapsed < self.CMD_INTERVAL:
                time.sleep(self.CMD_INTERVAL - elapsed)

            cmd_bytes = self._build_command(command, data)
            self.serial.write(cmd_bytes)
            self.last_cmd_time = time.time()

            logger.debug(f"Sent command: {command} {data}")
            return True

        except Exception as e:
            logger.error(f"Failed to send command: {e}")
            return False

    def send_command(self, command: str, data: str = ''):
        """Queue a command to be sent"""
        self.cmd_queue.put((command, data))

    def _process_commands(self):
        """Process command queue (runs in separate thread)"""
        while self.running:
            try:
                if not self.cmd_queue.empty():
                    command, data = self.cmd_queue.get(timeout=0.1)
                    self._send_command_now(command, data)
                else:
                    time.sleep(0.01)
            except Exception as e:
                logger.error(f"Command processing error: {e}")

    def _read_response(self) -> Optional[tuple[str, str]]:
        """Read and parse response from device"""
        if not self.serial or not self.serial.is_open:
            return None

        try:
            # Read available data
            if self.serial.in_waiting > 0:
                data = self.serial.read(self.serial.in_waiting)
                self.response_buffer.extend(data)

            # Look for complete message (LF...CR)
            if b'\r' in self.response_buffer:
                # Find message boundaries
                cr_idx = self.response_buffer.index(b'\r')
                message = self.response_buffer[:cr_idx]
                self.response_buffer = self.response_buffer[cr_idx + 1:]

                # Parse message
                if len(message) >= 3 and message[0] == 0x0A:  # LF
                    msg_str = message[1:].decode('ascii', errors='ignore')
                    if len(msg_str) >= 3:
                        machine_id = msg_str[0]
                        command = msg_str[1:3]
                        data = msg_str[3:] if len(msg_str) > 3 else ''

                        logger.debug(f"Received: cmd={command} data={data}")
                        return command, data

        except Exception as e:
            logger.error(f"Response read error: {e}")

        return None

    def _poll_status(self):
        """Poll device status periodically with auto-reconnect"""
        poll_count = 0
        while self.running:
            try:
                # If not connected, attempt reconnection
                if not self.connected:
                    current_time = time.time()
                    if current_time - self.last_reconnect_attempt >= self.reconnect_interval:
                        self.last_reconnect_attempt = current_time
                        logger.info("Attempting to reconnect to device...")
                        if self.connect():
                            logger.info("Reconnected successfully!")
                            self.consecutive_failures = 0
                        else:
                            logger.debug("Reconnection failed, will retry...")
                    time.sleep(1.0)
                    continue

                # Read any incoming responses
                response = self._read_response()
                got_response = False

                if response:
                    self._handle_response(*response)
                    got_response = True
                    self.consecutive_failures = 0  # Reset on successful response

                # Poll status
                self.send_command(self.CMD_MECHA_STATUS_SENSE)
                time.sleep(0.1)
                self.send_command(self.CMD_TRACK_NO_SENSE)
                time.sleep(0.1)
                self.send_command(self.CMD_CURRENT_TRACK_TIME_SENSE, '00')

                # Poll additional info less frequently (every 10 polls = ~3 seconds)
                if poll_count % 10 == 0:
                    time.sleep(0.1)
                    self.send_command(self.CMD_MEDIA_STATUS_SENSE)
                    time.sleep(0.1)
                    self.send_command(self.CMD_CURRENT_TRACK_INFO_SENSE)
                    time.sleep(0.1)
                    self.send_command(self.CMD_TOTAL_TRACK_TIME_SENSE)
                    time.sleep(0.1)
                    self.send_command(self.CMD_PLAY_MODE_SENSE)
                    time.sleep(0.1)
                    # Query current device
                    self.send_command(self.CMD_DEVICE_SELECT, 'FF')

                # Poll mode settings even less frequently (every 30 polls = ~9 seconds)
                if poll_count % 30 == 0:
                    time.sleep(0.1)
                    self.send_command(self.CMD_RESUME_PLAY_SENSE)
                    time.sleep(0.1)
                    self.send_command(self.CMD_REPEAT_SENSE)
                    time.sleep(0.1)
                    self.send_command(self.CMD_INCR_PLAY_SENSE)
                    time.sleep(0.1)
                    self.send_command(self.CMD_REMOTE_LOCAL_SENSE)

                # Track health: if we didn't get a response, increment failure count
                if not got_response:
                    self.consecutive_failures += 1
                    if self.consecutive_failures >= self.max_failures_before_disconnect:
                        logger.warning(f"Device not responding ({self.consecutive_failures} consecutive failures). Auto-disconnecting...")
                        self.disconnect()
                        continue

                poll_count += 1
                time.sleep(self.STATUS_POLL_INTERVAL)

            except Exception as e:
                logger.error(f"Status polling error: {e}")
                self.consecutive_failures += 1
                if self.consecutive_failures >= self.max_failures_before_disconnect:
                    logger.warning("Too many errors. Auto-disconnecting...")
                    self.disconnect()
                else:
                    time.sleep(1.0)

    def _handle_response(self, command: str, data: str):
        """Handle response from device"""
        updated = False

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
            self.current_status['mecha_status'] = status_map.get(data[:2], 'unknown')
            updated = True

        elif command == self.RET_TRACK_NO:
            # Parse track number (format: tens, ones, thousands, hundreds)
            if len(data) >= 4:
                tens = int(data[0])
                ones = int(data[1])
                thousands = int(data[2])
                hundreds = int(data[3])
                track_num = thousands * 1000 + hundreds * 100 + tens * 10 + ones
                self.current_status['track_number'] = track_num
                updated = True

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
                self.current_status['time_elapsed'] = f"{minutes:02d}:{seconds:02d}"
                updated = True

        elif command == self.RET_MEDIA_STATUS:
            # Parse media status (4 bytes: media present, media type)
            if len(data) >= 4:
                self.current_status['media_present'] = (data[:2] == '01')
                media_type_code = data[2:4]
                media_type_map = {
                    '00': 'CD-DA/Audio',
                    '10': 'CD-ROM/Data'
                }
                self.current_status['media_type'] = media_type_map.get(media_type_code, 'Unknown')
                updated = True

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
                self.current_status['current_track'] = current_track
                updated = True

        elif command == self.RET_PLAY_MODE:
            # Parse play mode (2 bytes)
            if len(data) >= 2:
                mode_map = {
                    '00': 'continuous',
                    '01': 'single',
                    '06': 'random'
                }
                self.current_status['play_mode'] = mode_map.get(data[:2], 'continuous')
                updated = True

        elif command == self.RET_TOTAL_TRACK_TIME:
            # Parse total tracks and total time (12 bytes)
            if len(data) >= 12:
                # Total tracks (bytes 0-3: tens, ones, thousands, hundreds)
                tens = int(data[0])
                ones = int(data[1])
                thousands = int(data[2])
                hundreds = int(data[3])
                total_tracks = thousands * 1000 + hundreds * 100 + tens * 10 + ones
                self.current_status['total_tracks'] = total_tracks

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
                    self.current_status['total_time'] = f"{minutes:02d}:{seconds:02d}"
                updated = True

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
                            self.current_status['device'] = device_code
                            self.current_status['device_name'] = device_name
                            self.current_status['is_tuner'] = device_code in ['fm', 'am']
                            updated = True
                            logger.debug(f"Device changed to: {device_name}")

        elif command == self.RET_RESUME_PLAY:
            # B5: Resume mode return
            if len(data) >= 2:
                self.current_status['resume_mode'] = (data[:2] == '01')
                updated = True

        elif command == self.RET_REPEAT:
            # B8: Repeat mode return
            if len(data) >= 2:
                self.current_status['repeat_mode'] = (data[:2] == '01')
                updated = True

        elif command == self.RET_INCR_PLAY:
            # BB: Incremental play return
            if len(data) >= 2:
                self.current_status['incremental_play'] = (data[:2] == '01')
                updated = True

        elif command == self.RET_REMOTE_LOCAL:
            # CD: Remote/local mode return
            if len(data) >= 2:
                mode_map = {
                    '00': 'remote_only',
                    '01': 'remote_and_local'
                }
                self.current_status['remote_local_mode'] = mode_map.get(data[:2], 'unknown')
                updated = True

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

                self.current_status['error_status'] = {
                    'raw': error_byte,
                    'errors': errors,
                    'has_error': len(errors) > 0
                }
                updated = True
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

                self.current_status['caution_status'] = {
                    'raw': caution_byte,
                    'cautions': cautions,
                    'has_caution': len(cautions) > 0
                }
                updated = True
                if cautions:
                    logger.info(f"Device cautions: {', '.join(cautions)}")

        elif command == self.RET_CHANGE_STATUS:
            # F6: Status changed - trigger immediate poll
            logger.info("Status changed notification received")
            # Query device to update status
            self.send_command(self.CMD_DEVICE_SELECT, 'FF')

        elif command == self.RET_ERROR_SENSE_REQUEST:
            # F0: Error occurred - query error details
            self.send_command(self.CMD_ERROR_SENSE)

        elif command == self.RET_CAUTION_SENSE_REQUEST:
            # F1: Caution state - query caution details
            self.send_command(self.CMD_CAUTION_SENSE)

        elif command == self.RET_ILLEGAL_STATUS:
            logger.warning("Illegal command/status received")

        # Notify callbacks if status updated
        if updated:
            self._notify_callbacks()

    def _notify_callbacks(self):
        """Notify all registered callbacks of status update"""
        for callback in self.status_callbacks:
            try:
                callback(self.current_status.copy())
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def register_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Register a callback for status updates"""
        self.status_callbacks.append(callback)

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
            self.current_status['play_mode'] = mode
        else:
            logger.error(f"Invalid play mode: {mode}")

    def set_repeat(self, enabled: bool):
        """Enable/disable repeat mode"""
        data = '01' if enabled else '00'
        self.send_command(self.CMD_REPEAT_SELECT, data)
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

        device_lower = device.lower()
        if device_lower in device_map:
            # Vendor command format: 7F01 (command) + device code (data)
            # Creates: LF 0 7F01 <device_code> CR
            self.send_command(self.CMD_DEVICE_SELECT, device_map[device_lower])
            self.current_status['device'] = device_lower

            # Update device name and type
            device_names = {
                'sd': 'SD Card',
                'usb': 'USB',
                'cd': 'CD',
                'bluetooth': 'Bluetooth',
                'fm': 'FM Radio',
                'am': 'AM Radio',
                'aux': 'AUX Input'
            }
            self.current_status['device_name'] = device_names.get(device_lower, device.upper())

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
        """Get current device status"""
        return self.current_status.copy()
