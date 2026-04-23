"""
TASCAM CD-400U Web Control Interface
Flask application with WebSocket support
"""

import os
import atexit
import signal
import sys
from functools import wraps
from threading import RLock

from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import logging
from tascam_controller import TascamController

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('TASCAM_SECRET_KEY', 'tascam-cd400u-dev-key')
cors_origins = os.environ.get('TASCAM_CORS_ORIGINS', '*')
CORS(app, origins=cors_origins.split(',') if cors_origins != '*' else '*')

# Initialize SocketIO
socketio = SocketIO(
    app,
    cors_allowed_origins=cors_origins if cors_origins == '*' else cors_origins.split(','),
    async_mode='threading'
)

# Global controller instance with lock
controller: TascamController = None
controller_lock = RLock()


# --- Helpers ---

def parse_bool(value, default=False):
    """Normalize a JSON value to bool (handles string 'false' truthiness bug)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes')
    return default


def require_connection(f):
    """Decorator: acquires controller lock, checks connection, wraps errors."""
    @wraps(f)
    def decorated(*args, **kwargs):
        with controller_lock:
            if not controller or not controller.connected:
                return jsonify({'success': False, 'message': 'Not connected'}), 400
            try:
                return f(*args, **kwargs)
            except Exception as e:
                logger.error(f"{f.__name__} failed: {e}")
                return jsonify({'success': False, 'message': str(e)}), 500
    return decorated


def status_callback(status: dict):
    """Callback for status updates from controller - broadcasts to ALL clients"""
    try:
        socketio.emit('status_update', status, broadcast=True)
        logger.debug(f"Status broadcast to all clients: {status}")
    except Exception as e:
        logger.error(f"Failed to broadcast status: {e}")


def cleanup():
    """Graceful shutdown: disconnect controller if active."""
    global controller
    with controller_lock:
        if controller:
            logger.info("Shutting down: disconnecting controller...")
            controller.disconnect()
            controller = None

atexit.register(cleanup)


def signal_handler(sig, frame):
    """Handle SIGTERM/SIGINT for clean systemd stops."""
    logger.info(f"Received signal {sig}, shutting down...")
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


# --- Routes ---

@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')


@app.route('/service-worker.js')
def service_worker():
    """Serve the service worker from the site root so it can claim scope '/'.

    A service worker hosted under /static/ would only control /static/* by
    default. Serving it from the root keeps the whole app installable.
    """
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
    """Get current device status"""
    with controller_lock:
        if controller and controller.connected:
            return jsonify({'connected': True, 'status': controller.get_status()})
        return jsonify({'connected': False, 'status': None})


@app.route('/api/connect', methods=['POST'])
def connect():
    """Connect to TASCAM device"""
    global controller

    data = request.get_json() or {}
    port = data.get('port', '/dev/ttyUSB0')
    baudrate = data.get('baudrate', 9600)

    try:
        baudrate = int(baudrate)
    except (TypeError, ValueError):
        return jsonify({
            'success': False,
            'message': 'Invalid baudrate. Must be an integer.'
        }), 400

    if baudrate not in TascamController.VALID_BAUDRATES:
        return jsonify({
            'success': False,
            'message': f'Invalid baudrate. Must be one of: {", ".join(map(str, TascamController.VALID_BAUDRATES))}'
        }), 400

    with controller_lock:
        try:
            if controller:
                controller.disconnect()

            controller = TascamController(port=port, baudrate=baudrate)
            controller.register_callback(status_callback)

            if controller.connect():
                logger.info(f"Connected to {port} at {baudrate} baud")
                return jsonify({
                    'success': True,
                    'message': f'Connected to {port} at {baudrate} baud'
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to connect to device'
                }), 500

        except ValueError as e:
            logger.error(f"Connection validation error: {e}")
            return jsonify({'success': False, 'message': str(e)}), 400
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    """Disconnect from TASCAM device"""
    global controller

    with controller_lock:
        if controller:
            controller.disconnect()
            controller = None
        logger.info("Disconnected from device")

    return jsonify({'success': True, 'message': 'Disconnected'})


# --- Transport controls ---

@app.route('/api/play', methods=['POST'])
@require_connection
def play():
    """Start playback"""
    controller.play()
    logger.info("Command: play")
    return jsonify({'success': True})


@app.route('/api/stop', methods=['POST'])
@require_connection
def stop():
    """Stop playback"""
    controller.stop()
    logger.info("Command: stop")
    return jsonify({'success': True})


@app.route('/api/eject', methods=['POST'])
@require_connection
def eject():
    """Eject CD"""
    controller.eject()
    logger.info("Command: eject")
    return jsonify({'success': True})


@app.route('/api/next', methods=['POST'])
@require_connection
def next_track():
    """Skip to next track"""
    controller.next_track()
    logger.info("Command: next track")
    return jsonify({'success': True})


@app.route('/api/previous', methods=['POST'])
@require_connection
def previous_track():
    """Skip to previous track"""
    controller.previous_track()
    logger.info("Command: previous track")
    return jsonify({'success': True})


@app.route('/api/track/<int:track_number>', methods=['POST'])
@require_connection
def goto_track(track_number):
    """Go to specific track"""
    controller.goto_track(track_number)
    logger.info(f"Command: goto track {track_number}")
    return jsonify({'success': True})


@app.route('/api/mode/<mode>', methods=['POST'])
@require_connection
def set_mode(mode):
    """Set playback mode"""
    if mode not in ('continuous', 'single', 'random'):
        return jsonify({'success': False, 'message': 'Invalid mode'}), 400
    controller.set_play_mode(mode)
    logger.info(f"Command: set mode {mode}")
    return jsonify({'success': True})


@app.route('/api/repeat', methods=['POST'])
@require_connection
def set_repeat():
    """Toggle repeat mode"""
    data = request.get_json() or {}
    enabled = parse_bool(data.get('enabled', False))
    controller.set_repeat(enabled)
    logger.info(f"Command: repeat {'on' if enabled else 'off'}")
    return jsonify({'success': True})


@app.route('/api/pause', methods=['POST'])
@require_connection
def pause():
    """Pause playback"""
    controller.pause()
    logger.info("Command: pause")
    return jsonify({'success': True})


@app.route('/api/resume', methods=['POST'])
@require_connection
def resume():
    """Resume from pause"""
    controller.resume()
    logger.info("Command: resume")
    return jsonify({'success': True})


@app.route('/api/search/start', methods=['POST'])
@require_connection
def search_start():
    """Start searching"""
    data = request.get_json() or {}
    forward = parse_bool(data.get('forward', True), default=True)
    high_speed = parse_bool(data.get('high_speed', False))
    controller.search_start(forward=forward, high_speed=high_speed)
    direction = 'forward' if forward else 'reverse'
    speed = ' (high speed)' if high_speed else ''
    logger.info(f"Command: search {direction}{speed}")
    return jsonify({'success': True})


@app.route('/api/search/stop', methods=['POST'])
@require_connection
def search_stop():
    """Stop searching"""
    controller.search_stop()
    logger.info("Command: search stop")
    return jsonify({'success': True})


@app.route('/api/resume-mode', methods=['POST'])
@require_connection
def set_resume_mode():
    """Toggle resume mode"""
    data = request.get_json() or {}
    enabled = parse_bool(data.get('enabled', False))
    controller.set_resume_mode(enabled)
    logger.info(f"Command: resume mode {'on' if enabled else 'off'}")
    return jsonify({'success': True})


@app.route('/api/device/<device>', methods=['POST'])
@require_connection
def switch_device(device):
    """Switch input source"""
    valid_devices = ('cd', 'usb', 'sd', 'bluetooth', 'fm', 'am', 'dab', 'aux')
    if device.lower() not in valid_devices:
        return jsonify({'success': False, 'message': 'Invalid device'}), 400
    controller.switch_device(device)
    logger.info(f"Command: switch device to {device}")
    return jsonify({'success': True})


# --- Tuner controls ---

@app.route('/api/tuner/frequency/up', methods=['POST'])
@require_connection
def tuner_frequency_up():
    """Tune frequency up"""
    controller.tuner_frequency_up()
    logger.info("Command: tuner frequency up")
    return jsonify({'success': True})


@app.route('/api/tuner/frequency/down', methods=['POST'])
@require_connection
def tuner_frequency_down():
    """Tune frequency down"""
    controller.tuner_frequency_down()
    logger.info("Command: tuner frequency down")
    return jsonify({'success': True})


@app.route('/api/tuner/seek/up', methods=['POST'])
@require_connection
def tuner_seek_up():
    """Auto-seek next station"""
    controller.tuner_seek_up()
    logger.info("Command: tuner seek up")
    return jsonify({'success': True})


@app.route('/api/tuner/seek/down', methods=['POST'])
@require_connection
def tuner_seek_down():
    """Auto-seek previous station"""
    controller.tuner_seek_down()
    logger.info("Command: tuner seek down")
    return jsonify({'success': True})


@app.route('/api/tuner/preset/<int:preset>', methods=['POST'])
@require_connection
def tuner_preset(preset):
    """Select tuner preset"""
    controller.tuner_preset(preset)
    logger.info(f"Command: tuner preset {preset}")
    return jsonify({'success': True})


# --- WebSocket events ---

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info('Client connected')
    with controller_lock:
        if controller and controller.connected:
            emit('status_update', controller.get_status())


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info('Client disconnected')


@socketio.on('request_status')
def handle_request_status():
    """Handle status request from client"""
    with controller_lock:
        if controller and controller.connected:
            emit('status_update', controller.get_status())


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='TASCAM CD-400U Web Controller')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    parser.add_argument('--serial-port',
                        default='/dev/serial/by-id/usb-FTDI_USB_Serial_Converter_FTEM3Y6M-if00-port0',
                        help='Serial port (using persistent by-id path)')
    parser.add_argument('--baudrate', type=int, default=9600, help='Baud rate')
    parser.add_argument('--auto-connect', action='store_true', help='Auto-connect on startup')

    args = parser.parse_args()

    # Auto-connect if requested
    if args.auto_connect:
        try:
            controller = TascamController(port=args.serial_port, baudrate=args.baudrate)
            controller.register_callback(status_callback)
            if controller.connect():
                logger.info(f"Auto-connected to {args.serial_port}")
            else:
                logger.warning("Auto-connect failed")
                controller = None
        except Exception as e:
            logger.error(f"Auto-connect error: {e}")
            controller = None

    # Start periodic state sync to keep all clients synchronized
    def periodic_state_sync():
        """Broadcast full state every 3 seconds to all clients"""
        while True:
            time.sleep(3)
            try:
                with controller_lock:
                    if controller and controller.connected:
                        status = controller.get_status()
                        socketio.emit('status_update', status, broadcast=True)
                        logger.debug("Periodic state sync broadcast")
            except Exception as e:
                logger.error(f"Periodic sync error: {e}")

    import threading
    import time
    sync_thread = threading.Thread(target=periodic_state_sync, daemon=True)
    sync_thread.start()
    logger.info("Started periodic state sync (3s interval)")

    # Start server
    logger.info(f"Starting server on {args.host}:{args.port}")
    socketio.run(app, host=args.host, port=args.port, debug=False, allow_unsafe_werkzeug=True)
