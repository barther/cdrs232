"""
TASCAM CD-400U Web Control Interface
Flask application with WebSocket support
"""

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import logging
import json
from tascam_controller import TascamController

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'tascam-cd400u-secret-key-change-in-production'
CORS(app)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global controller instance
controller: TascamController = None


def status_callback(status: dict):
    """Callback for status updates from controller"""
    try:
        socketio.emit('status_update', status, broadcast=True)
        logger.debug(f"Status update broadcast: {status}")
    except Exception as e:
        logger.error(f"Failed to broadcast status: {e}")


@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')


@app.route('/api/status', methods=['GET'])
def get_status():
    """Get current device status"""
    if controller and controller.connected:
        return jsonify({
            'connected': True,
            'status': controller.get_status()
        })
    else:
        return jsonify({
            'connected': False,
            'status': None
        })


@app.route('/api/connect', methods=['POST'])
def connect():
    """Connect to TASCAM device"""
    global controller

    data = request.get_json() or {}
    port = data.get('port', '/dev/ttyUSB0')
    baudrate = data.get('baudrate', 9600)

    try:
        if controller:
            controller.disconnect()

        controller = TascamController(port=port, baudrate=baudrate)
        controller.register_callback(status_callback)

        if controller.connect():
            return jsonify({
                'success': True,
                'message': f'Connected to {port} at {baudrate} baud'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to connect to device'
            }), 500

    except Exception as e:
        logger.error(f"Connection error: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    """Disconnect from TASCAM device"""
    global controller

    if controller:
        controller.disconnect()
        controller = None

    return jsonify({
        'success': True,
        'message': 'Disconnected'
    })


# Transport control endpoints
@app.route('/api/play', methods=['POST'])
def play():
    """Start playback"""
    if controller and controller.connected:
        controller.play()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Not connected'}), 400


@app.route('/api/stop', methods=['POST'])
def stop():
    """Stop playback"""
    if controller and controller.connected:
        controller.stop()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Not connected'}), 400


@app.route('/api/eject', methods=['POST'])
def eject():
    """Eject CD"""
    if controller and controller.connected:
        controller.eject()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Not connected'}), 400


@app.route('/api/next', methods=['POST'])
def next_track():
    """Skip to next track"""
    if controller and controller.connected:
        controller.next_track()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Not connected'}), 400


@app.route('/api/previous', methods=['POST'])
def previous_track():
    """Skip to previous track"""
    if controller and controller.connected:
        controller.previous_track()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Not connected'}), 400


@app.route('/api/track/<int:track_number>', methods=['POST'])
def goto_track(track_number):
    """Go to specific track"""
    if controller and controller.connected:
        controller.goto_track(track_number)
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Not connected'}), 400


@app.route('/api/mode/<mode>', methods=['POST'])
def set_mode(mode):
    """Set playback mode"""
    if controller and controller.connected:
        if mode in ['continuous', 'single', 'random']:
            controller.set_play_mode(mode)
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Invalid mode'}), 400
    return jsonify({'success': False, 'message': 'Not connected'}), 400


@app.route('/api/repeat', methods=['POST'])
def set_repeat():
    """Toggle repeat mode"""
    if controller and controller.connected:
        data = request.get_json() or {}
        enabled = data.get('enabled', False)
        controller.set_repeat(enabled)
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Not connected'}), 400


@app.route('/api/pause', methods=['POST'])
def pause():
    """Pause playback"""
    if controller and controller.connected:
        controller.pause()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Not connected'}), 400


@app.route('/api/resume', methods=['POST'])
def resume():
    """Resume from pause"""
    if controller and controller.connected:
        controller.resume()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Not connected'}), 400


@app.route('/api/search/start', methods=['POST'])
def search_start():
    """Start searching"""
    if controller and controller.connected:
        data = request.get_json() or {}
        forward = data.get('forward', True)
        high_speed = data.get('high_speed', False)
        controller.search_start(forward=forward, high_speed=high_speed)
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Not connected'}), 400


@app.route('/api/search/stop', methods=['POST'])
def search_stop():
    """Stop searching"""
    if controller and controller.connected:
        controller.search_stop()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Not connected'}), 400


@app.route('/api/resume-mode', methods=['POST'])
def set_resume_mode():
    """Toggle resume mode"""
    if controller and controller.connected:
        data = request.get_json() or {}
        enabled = data.get('enabled', False)
        controller.set_resume_mode(enabled)
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Not connected'}), 400


@app.route('/api/device/<device>', methods=['POST'])
def switch_device(device):
    """Switch input source"""
    if controller and controller.connected:
        valid_devices = ['cd', 'usb', 'sd', 'bluetooth', 'fm', 'am', 'dab', 'aux']
        if device.lower() in valid_devices:
            controller.switch_device(device)
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Invalid device'}), 400
    return jsonify({'success': False, 'message': 'Not connected'}), 400


# WebSocket events
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info('Client connected')
    if controller and controller.connected:
        emit('status_update', controller.get_status())


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info('Client disconnected')


@socketio.on('request_status')
def handle_request_status():
    """Handle status request from client"""
    if controller and controller.connected:
        emit('status_update', controller.get_status())


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='TASCAM CD-400U Web Controller')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    parser.add_argument('--serial-port', default='/dev/ttyUSB0', help='Serial port')
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

    # Start server
    logger.info(f"Starting server on {args.host}:{args.port}")
    socketio.run(app, host=args.host, port=args.port, debug=False, allow_unsafe_werkzeug=True)
