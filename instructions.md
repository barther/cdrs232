# TASCAM CD-400U RS-232C Control Interface

## Project Overview

Web-based control interface for TASCAM CD-400U/CD-400UDAB professional CD player, designed to run on Raspberry Pi 3 with USB-to-RS232 adapter.

## Hardware Requirements

- Raspberry Pi 3 (or newer)
- USB to RS-232 adapter (FTDI chip recommended)
- TASCAM CD-400U or CD-400UDAB
- Standard RS-232 cable (DB-9 female to DB-9 female)

## RS-232C Specifications

### Physical Connection

**Connector**: D-sub 9-pin female (inch screw thread)

**Pin Configuration**:
- Pin 2: RX DATA (Input)
- Pin 3: TX DATA (Output)
- Pin 5: GND (Signal ground)
- Pin 7: RTS (Short-circuited to Pin 8)
- Pin 8: CTS (Short-circuited to Pin 7)

### Communication Settings

- **Baud Rate**: 4800/9600/19200/38400/57600 bps (configurable on device)
- **Data Bits**: 8
- **Parity**: None
- **Stop Bits**: 1
- **Flow Control**: Hardware (RTS/CTS)

## Command Protocol

### Command Format

All commands follow this structure:

```
[LF][ID][COMMAND][DATA...][CR]
```

- **LF**: Line Feed (0x0A)
- **ID**: Machine ID (always '0' / 0x30)
- **COMMAND**: 2-byte ASCII command code
- **DATA**: 0-98 bytes of ASCII data
- **CR**: Carriage Return (0x0D)

**Minimum command interval**: 100ms between commands

### Core Transport Commands

| Command | Code | Data | Description |
|---------|------|------|-------------|
| STOP | 10 | None | Stop playback |
| PLAY | 12 | None | Start playback |
| READY | 14 | 2 bytes | Playback standby (01 = ON) |
| SEARCH | 16 | 2 bytes | Search forward/reverse |
| EJECT | 18 | None | Eject CD |
| TRACK SKIP | 1A | 2 bytes | Next/Previous track |

**TRACK SKIP Data**:
- `00`: Next track
- `01`: Previous track

**SEARCH Data**:
- `00`: Forward (normal speed)
- `01`: Reverse (normal speed)
- `10`: Forward (high speed)
- `11`: Reverse (high speed)

### Track Selection

**DIRECT TRACK SEARCH PRESET** (Command: 23)

Data format (4 bytes): `[Tens][Ones][Thousands][Hundreds]`

Example - Track 123:
```
LF 0 2 3 2 3 0 1 CR
0A 30 32 33 32 33 30 31 0D
```

### Playback Mode Commands

| Command | Code | Data | Description |
|---------|------|------|-------------|
| RESUME PLAY SELECT | 34 | 2 bytes | Resume mode ON/OFF |
| REPEAT SELECT | 37 | 2 bytes | Repeat mode ON/OFF |
| INCR PLAY SELECT | 3A | 2 bytes | Incremental playback ON/OFF |
| PLAY MODE SELECT | 4D | 2 bytes | Set playback mode |

**PLAY MODE SELECT Data**:
- `00`: Continuous playback
- `01`: Single track playback
- `06`: Random playback

**Mode Control Data** (Resume/Repeat/Incr):
- `00`: OFF
- `01`: ON
- `FF`: Sense (request current state)

### Status Query Commands

| Command | Code | Returns | Description |
|---------|------|---------|-------------|
| INFORMATION REQUEST | 0F | 8F | Software version |
| MECHA STATUS SENSE | 50 | D0 | Current mechanism status |
| TRACK NO. SENSE | 55 | D5 | Current track number |
| MEDIA STATUS SENSE | 56 | D6 | Media presence/type |
| CURRENT TRACK INFO SENSE | 57 | D7 | Track information |
| CURRENT TRACK TIME SENSE | 58 | D8 | Time information |
| PLAY MODE SENSE | 4E | CE | Current playback mode |

**CURRENT TRACK TIME SENSE Data**:
- `00`: Track elapsed time
- `01`: Track remaining time (CD-DA only)
- `02`: Total elapsed time (CD-DA only)
- `03`: Total remaining time (CD-DA only)

### Device Control Commands

**REMOTE/LOCAL SELECT** (Command: 4C)

| Data | Mode | Front Panel | RS-232C | IR Remote |
|------|------|-------------|---------|-----------|
| 00 | Only remote | Disabled | Enabled | Enabled |
| 01 | Remote and front | Enabled | Enabled | Enabled |
| 10 | Serial only | Disabled | Enabled | Disabled |
| 11 | IR disabled | Enabled | Enabled | Disabled |

**DEVICE SELECT** (Vendor Command: 7F01)

| Data | Device |
|------|--------|
| 00 | SD Card |
| 10 | USB |
| 11 | CD |
| 20 | Bluetooth |
| 30 | FM (CD-400U) / DAB (CD-400UDAB) |
| 31 | AM (CD-400U) / FM (CD-400UDAB) |
| 40 | AUX |
| FF | Sense (query current) |

### Return Commands

**MECHA STATUS RETURN** (Command: D0)

| Data | Status |
|------|--------|
| 00 | No media |
| 01 | Ejecting |
| 10 | Stop |
| 11 | Play |
| 12 | Ready |
| 28 | Searching forward |
| 29 | Searching backward |
| 81 | Recording |
| 82 | Record ready |
| 83 | Writing info |
| FF | Other |

**MEDIA STATUS RETURN** (Command: D6)

Data structure (4 bytes):
- Bytes 1-2: Media status (00 = no media, 01 = loaded)
- Bytes 3-4: Media type (00 = CD-DA/SD/USB, 10 = CD-ROM/Data)

**TRACK NO. RETURN** (Command: D5)

Data structure (4 bytes): `[Tens][Ones][Thousands][Hundreds]`

Example - Track 123:
```
Data: 2 3 0 1
```

**CURRENT TRACK TIME RETURN** (Command: D8)

Data structure (10 bytes):
- Bytes 1-2: Time type (00=elapsed, 01=remaining, etc.)
- Bytes 3-4: Minutes (tens, ones)
- Bytes 5-6: Minutes (thousands, hundreds)
- Bytes 7-8: Seconds (tens, ones)
- Bytes 9-10: Frames (always 0)

### Error Handling

**Asynchronous Status Commands** (from device):

| Command | Code | Description |
|---------|------|-------------|
| ERROR SENSE REQUEST | F0 | Error occurred - use ERROR SENSE (78) |
| CAUTION SENSE REQUEST | F1 | Caution state - use CAUTION SENSE (79) |
| ILLEGAL STATUS | F2 | Invalid command/data received |
| POWER ON STATUS | F4 | Device powered on |
| CHANGE STATUS | F6 | Status changed |

**CHANGE STATUS Data**:
- `00`: Mechanism status changed
- `03`: Track/tuner changed or EOM

**ERROR SENSE RETURN** (Command: F8)

Data format: `[N2][N3][0][N1]` (error code N1-N2N3)
- `0-00`: No error
- `1-01`: Dubbing error (recording)
- `1-02`: Device error
- `1-FF`: Other error

**CAUTION SENSE RETURN** (Command: F9)

Common caution codes:
- `0-00`: No caution
- `1-02`: Media error
- `1-06`: Media full
- `1-0C`: Write protected
- `1-0D`: Cannot execute
- `1-13`: Cannot select
- `1-1E`: Decode error
- `1-1F`: Media not match
- `1-FF`: Other caution

## Implementation Guidelines

### Timing Requirements

1. **Command Spacing**: Minimum 100ms between commands
2. **Response Timeout**: Wait up to 500ms for return commands
3. **Status Polling**: Query status every 250-500ms during playback

### Command Sequence Examples

**Starting Playback**:
```
1. Send PLAY command (12)
2. Wait for CHANGE STATUS (F6) with data 00
3. Query MECHA STATUS SENSE (50) to confirm playback state
```

**Selecting Track**:
```
1. Send DIRECT TRACK SEARCH PRESET (23) with track number
2. Device changes track (no ACK sent)
3. Device sends CHANGE STATUS (F6) with data 03
```

**Querying Current State**:
```
1. Send TRACK NO. SENSE (55)
2. Receive TRACK NO. RETURN (D5) with track number
3. Send CURRENT TRACK TIME SENSE (58) with data 00
4. Receive CURRENT TRACK TIME RETURN (D8) with elapsed time
```

### Error Recovery

1. If ILLEGAL STATUS (F2) received, verify command format and retry
2. If ERROR SENSE REQUEST (F0) received, immediately send ERROR SENSE (78)
3. If no response within timeout, resend command (max 3 retries)
4. Implement reconnection logic for serial port disconnection

## Technical Notes

### Voltage Specifications

- **Signal Logic "1"**: -3V or less
- **Signal Logic "0"**: +3V or more
- **Receiver Impedance**: 3k-7k ohms (DC resistance)
- **Total Load Capacitance**: ≤2500 pF

### Track Number Limitations

- **Audio CD**: 1-99 tracks
- **MP3/WAV Media**: 1-999 tracks

### Vendor Command Format

Vendor commands (7F/FF) have extended format:

```
[LF][ID][7F/FF][Category][SubCommand][Parameters...][CR]
```

Example - Device Select to USB:
```
LF 0 7F 01 10 CR
0A 30 37 46 30 31 31 30 0D
```

## Development Stack Recommendations

### Backend
- **Language**: Python 3.7+
- **Serial Library**: `pyserial`
- **Web Framework**: Flask or FastAPI
- **WebSocket**: `python-socketio` for real-time updates

### Frontend
- **Framework**: Vanilla JS or lightweight framework (Alpine.js, Svelte)
- **UI**: Mobile-first responsive design
- **Real-time**: WebSocket for status updates
- **PWA**: Service worker for offline capability

### System Configuration

**Enable Serial Port on Raspberry Pi**:
```bash
sudo raspi-config
# Interface Options -> Serial Port
# Login shell: No
# Serial port hardware: Yes
```

**Find USB Serial Device**:
```bash
ls -l /dev/ttyUSB*
# or
dmesg | grep tty
```

**Set Permissions**:
```bash
sudo usermod -a -G dialout $USER
```

## Safety Considerations

1. Never send commands faster than 100ms intervals
2. Implement command queue with proper timing
3. Handle device disconnection gracefully
4. Validate all user inputs before sending commands
5. Monitor ERROR/CAUTION responses continuously
6. Implement watchdog for serial communication health

## Reference Materials

- TASCAM CD-400U/CD-400UDAB RS-232C Protocol Specification v1.21
- Standard: JIS X-5101 (equivalent to EIA RS-232C)
- Firmware Version: Check with INFORMATION REQUEST (0F) command

## License & Legal

**IMPORTANT**: This protocol is proprietary to TEAC Corporation. Usage requires:
- Acceptance of TEAC protocol use agreement
- Nonexclusive, nontransferable usage rights
- No redistribution of protocol documentation without permission
- No warranties provided by TEAC
- Use at own risk

Review full legal terms in TASCAM protocol specification document before implementation.
