"""
TASCAM CD-400U Web Control Interface

Serves the control page and a small JSON API. The controller owns the serial
port and keeps polling the deck; the page polls /api/status and POSTs
commands. No WebSocket layer: every status reply is complete, so a phone that
sleeps, loses Wi-Fi or joins late just catches up on its next poll.
"""

import argparse
import atexit
import logging
import signal
import sys
from functools import wraps

from flask import Flask, jsonify, render_template, request, send_from_directory

from tascam_controller import DEFAULT_PORT, TascamController

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
# The page polls a few times a second; don't log every request.
logging.getLogger('werkzeug').setLevel(logging.WARNING)

app = Flask(__name__)

# The one controller for the deck, created at startup.
controller: TascamController = None


# --- Helpers ---

def parse_bool(value, default=False):
    """Normalize a JSON value to bool (handles string 'false' truthiness bug)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes')
    return default


def deck_command(f):
    """Only run a command while the deck is answering, so a press made while
    it's off can't fire later when it comes back. A route that returns None
    means success."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if controller is None or not controller.online:
            return jsonify({'success': False, 'message': 'CD player is not responding'}), 503
        result = f(*args, **kwargs)
        if result is not None:
            return result
        logger.info(f"Command: {request.path}")
        return jsonify({'success': True})
    return decorated


def cleanup():
    """Graceful shutdown: stop polling and close the port."""
    if controller:
        controller.shutdown()


atexit.register(cleanup)


def signal_handler(sig, frame):
    """Handle SIGTERM/SIGINT for clean systemd stops."""
    logger.info(f"Received signal {sig}, shutting down...")
    sys.exit(0)  # atexit runs cleanup()


# --- Routes ---

@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')


@app.route('/service-worker.js')
def service_worker():
    """Serve the service worker from the site root so it can claim scope '/'."""
    response = send_from_directory(
        app.static_folder, 'service-worker.js', mimetype='application/javascript'
    )
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response


@app.route('/manifest.webmanifest')
def manifest():
    """Serve the PWA manifest with the correct MIME type."""
    return send_from_directory(
        app.static_folder, 'manifest.webmanifest', mimetype='application/manifest+json'
    )


@app.route('/api/status', methods=['GET'])
def get_status():
    """Everything the page shows, including whether the deck is answering."""
    if controller is None:
        return jsonify({'online': False, 'port_open': False})
    response = jsonify(controller.get_status())
    response.headers['Cache-Control'] = 'no-store'
    return response


# --- Transport controls ---

@app.route('/api/play', methods=['POST'])
@deck_command
def play():
    controller.play()


@app.route('/api/stop', methods=['POST'])
@deck_command
def stop():
    controller.stop()


@app.route('/api/pause', methods=['POST'])
@deck_command
def pause():
    controller.pause()


@app.route('/api/resume', methods=['POST'])
@deck_command
def resume():
    controller.resume()


@app.route('/api/eject', methods=['POST'])
@deck_command
def eject():
    controller.eject()


@app.route('/api/next', methods=['POST'])
@deck_command
def next_track():
    controller.next_track()


@app.route('/api/previous', methods=['POST'])
@deck_command
def previous_track():
    controller.previous_track()


@app.route('/api/track/<int:track_number>', methods=['POST'])
@deck_command
def goto_track(track_number):
    if not 1 <= track_number <= 999:
        return jsonify({'success': False, 'message': 'Track must be 1-999'}), 400
    controller.goto_track(track_number)


@app.route('/api/search/start', methods=['POST'])
@deck_command
def search_start():
    data = request.get_json(silent=True) or {}
    controller.search_start(
        forward=parse_bool(data.get('forward', True), default=True),
        high_speed=parse_bool(data.get('high_speed', False)),
    )


@app.route('/api/search/stop', methods=['POST'])
@deck_command
def search_stop():
    controller.search_stop()


# --- Modes and source ---

@app.route('/api/mode/<mode>', methods=['POST'])
@deck_command
def set_mode(mode):
    if mode not in ('continuous', 'single', 'random'):
        return jsonify({'success': False, 'message': 'Invalid mode'}), 400
    controller.set_play_mode(mode)


@app.route('/api/repeat', methods=['POST'])
@deck_command
def set_repeat():
    data = request.get_json(silent=True) or {}
    controller.set_repeat(parse_bool(data.get('enabled', False)))


@app.route('/api/resume-mode', methods=['POST'])
@deck_command
def set_resume_mode():
    data = request.get_json(silent=True) or {}
    controller.set_resume_mode(parse_bool(data.get('enabled', False)))


@app.route('/api/device/<device>', methods=['POST'])
@deck_command
def switch_device(device):
    if device.lower() not in ('cd', 'usb', 'sd', 'bluetooth', 'fm', 'am', 'aux'):
        return jsonify({'success': False, 'message': 'Invalid device'}), 400
    controller.switch_device(device)


# --- Tuner controls ---

@app.route('/api/tuner/frequency/up', methods=['POST'])
@deck_command
def tuner_frequency_up():
    controller.tuner_frequency_up()


@app.route('/api/tuner/frequency/down', methods=['POST'])
@deck_command
def tuner_frequency_down():
    controller.tuner_frequency_down()


@app.route('/api/tuner/seek/up', methods=['POST'])
@deck_command
def tuner_seek_up():
    controller.tuner_seek_up()


@app.route('/api/tuner/seek/down', methods=['POST'])
@deck_command
def tuner_seek_down():
    controller.tuner_seek_down()


@app.route('/api/tuner/preset/<int:preset>', methods=['POST'])
@deck_command
def tuner_preset(preset):
    if not 1 <= preset <= 20:
        return jsonify({'success': False, 'message': 'Preset must be 1-20'}), 400
    controller.tuner_preset(preset)


def main():
    global controller

    parser = argparse.ArgumentParser(description='TASCAM CD-400U Web Controller')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    parser.add_argument('--serial-port', default=DEFAULT_PORT,
                        help='Serial port (using persistent by-id path)')
    parser.add_argument('--baudrate', type=int, default=9600,
                        choices=TascamController.VALID_BAUDRATES, help='Baud rate')
    # Connecting is automatic now (and retried until the adapter and deck
    # answer). The flag is still accepted so existing service files start.
    parser.add_argument('--auto-connect', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--sim', action='store_true',
                        help='Use a simulated deck instead of the serial port')
    args = parser.parse_args()

    serial_port = args.serial_port
    if args.sim:
        from tascam_sim import TascamSimulator
        serial_port = TascamSimulator().start()
        logger.info(f"Simulated CD-400U on {serial_port}")

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    controller = TascamController(port=serial_port, baudrate=args.baudrate)
    controller.start()

    logger.info(f"Starting server on {args.host}:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == '__main__':
    main()
