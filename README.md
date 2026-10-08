# TASCAM CD-400U Web Controller

A phone-friendly web page for controlling a TASCAM CD-400U/CD-400UDAB over
RS-232C, served from a Raspberry Pi with a USB-to-RS232 adapter.

## What it does

- Big track / time / status display that follows the deck within a fraction
  of a second
- Play/Pause, Stop, Previous/Next, tap a track number to cue it
- Source (CD/USB/SD/BT/FM/AM/AUX), play mode, repeat, hold-to-search, eject
- Clear status when something is wrong: Pi unreachable, USB adapter missing,
  or the deck switched off. It reconnects on its own when the problem clears.
- Any number of phones at once; they all show the same state
- Installable to the home screen (PWA)

## How it works

```
phone ──HTTP──> Flask (app.py) ──> TascamController ──RS-232──> CD-400U
```

- `tascam_controller.py` owns the serial port with one background thread.
  Each pass it applies **every** reply the deck has sent, then sends one
  command: a button press if one is waiting, otherwise the next status query.
  Commands are spaced 100 ms apart as the protocol requires. If the deck
  stops answering for 3 s it is reported offline; if the adapter disappears
  the port is reopened every 5 s.
- `app.py` serves the page and a small JSON API. Commands are refused while
  the deck is offline, so a press made then can't fire later.
- `templates/index.html` polls `/api/status` about three times a second. Every
  reply is the complete state, so a phone that sleeps or drops Wi-Fi simply
  catches up on its next poll. There is no WebSocket layer to fall out of sync.

## Hardware

- Raspberry Pi 3 or newer
- USB to RS-232 adapter (FTDI recommended)
- TASCAM CD-400U or CD-400UDAB
- DB-9 female to DB-9 female RS-232 cable

## Install

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv git -y
sudo usermod -a -G dialout $USER   # serial port access; reboot afterwards

cd ~
git clone <repository-url> cdrs232
cd cdrs232
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
source venv/bin/activate
python app.py --serial-port /dev/serial/by-id/usb-FTDI_... --baudrate 9600
```

Then open `http://<pi-ip>:5000` on a phone on the same network
(`hostname -I` shows the Pi's address).

The controller connects by itself at startup and keeps retrying, so the Pi
can boot before the deck is switched on. Use the persistent
`/dev/serial/by-id/...` path rather than `/dev/ttyUSB0` (see
`USB_PORT_GUIDE.md`). The baud rate must match the deck's RS-232C setting.

### Options

```
--host HOST          Address to bind (default 0.0.0.0)
--port PORT          Web port (default 5000)
--serial-port PATH   Serial device (default: the FTDI by-id path)
--baudrate RATE      4800, 9600, 19200, 38400 or 57600 (default 9600)
--sim                Use a simulated deck instead of the serial port
```

`--auto-connect` is still accepted so existing service files keep working;
connecting is always automatic now.

### Try it without the deck

```bash
python app.py --sim
```

`tascam_sim.py` pretends to be a CD-400U on a pseudo-terminal: time runs
while playing, tracks advance, and the buttons do what they should.

## Run on boot (systemd)

`install-service.sh` creates and enables a service (edit the user, paths and
serial port at the top first). Or by hand:

```bash
sudo cp tascam-controller.service /etc/systemd/system/   # edit paths/user first
sudo systemctl enable --now tascam-controller.service
sudo journalctl -u tascam-controller.service -f          # logs
```

## Install as a home-screen app

- **iOS (Safari)**: Share → Add to Home Screen
- **Android (Chrome)**: menu → Install app

## RS-232C settings on the deck

8 data bits, no parity, 1 stop bit, baud rate matching `--baudrate`.
Pins 7 and 8 are shorted inside the deck, so no flow control is used.

## Troubleshooting

The status pill and the red notice under it say what's wrong:

| Shown | Meaning | Fix |
|-------|---------|-----|
| NO SERVER | The phone can't reach the Pi | Phone on the right Wi-Fi? Pi on? `systemctl status tascam-controller` |
| OFFLINE + "USB serial adapter isn't connected" | The serial port can't be opened | Check the USB adapter; check the `--serial-port` path; user in `dialout` group |
| OFFLINE + "CD player isn't answering" | Port is open but the deck is silent | Deck powered on? Cable seated? Baud rate matches the deck? |

`python test_serial.py` sends one status query and prints the raw reply,
which is handy for checking the cable and baud rate.

## API

All commands are `POST` and return `{"success": true}`, or 503 while the
deck is offline.

| Endpoint | Action |
|----------|--------|
| `GET /api/status` | Full state, plus `online` and `port_open` |
| `/api/play`, `/api/pause`, `/api/resume`, `/api/stop` | Transport |
| `/api/next`, `/api/previous`, `/api/track/<n>` | Track selection |
| `/api/search/start` `{"forward": true}`, `/api/search/stop` | Search |
| `/api/eject` | Eject |
| `/api/mode/<continuous\|single\|random>` | Play mode |
| `/api/repeat` `{"enabled": true}`, `/api/resume-mode` `{"enabled": true}` | Toggles |
| `/api/device/<cd\|usb\|sd\|bluetooth\|fm\|am\|aux>` | Source |
| `/api/tuner/frequency/<up\|down>`, `/api/tuner/seek/<up\|down>`, `/api/tuner/preset/<n>` | Tuner |

## Development

```
app.py                  Flask app + API
tascam_controller.py    RS-232 protocol and serial I/O
tascam_sim.py           Simulated deck for development and tests
templates/index.html    The page (no external dependencies)
static/                 PWA manifest, service worker, icons
tests/                  python -m unittest discover -s tests
instructions.md         Protocol notes
```

## Security

There is no login. Anyone on the network who can reach the Pi can control
the deck. Keep it on a private network.

## License & Legal

This software is provided as-is without warranty. The TASCAM RS-232C protocol
is proprietary to TEAC Corporation; use of it requires acceptance of TEAC's
protocol use agreement. See `instructions.md`.
