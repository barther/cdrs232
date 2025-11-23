#!/bin/bash

# TASCAM CD-400U Controller - Auto-Start Setup Script
# This script configures the controller to run automatically on boot

set -e

echo "=============================================="
echo "TASCAM CD-400U Auto-Start Configuration"
echo "=============================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ This script must be run as root (use sudo)"
    exit 1
fi

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-$USER}
if [ "$ACTUAL_USER" = "root" ]; then
    echo "❌ Please run with sudo as a normal user, not as root"
    exit 1
fi

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo "📁 Installation directory: $SCRIPT_DIR"
echo ""

# Prompt for configuration
echo "Configuration Options:"
echo "====================="
echo ""

# Serial port
read -p "Serial port [/dev/ttyUSB0]: " SERIAL_PORT
SERIAL_PORT=${SERIAL_PORT:-/dev/ttyUSB0}

# Baud rate
read -p "Baud rate [9600]: " BAUD_RATE
BAUD_RATE=${BAUD_RATE:-9600}

# Web server port
read -p "Web server port [5000]: " WEB_PORT
WEB_PORT=${WEB_PORT:-5000}

# Auto-connect
read -p "Auto-connect on startup? [Y/n]: " AUTO_CONNECT
AUTO_CONNECT=${AUTO_CONNECT:-Y}

echo ""
echo "Configuration Summary:"
echo "====================="
echo "Serial Port: $SERIAL_PORT"
echo "Baud Rate: $BAUD_RATE"
echo "Web Port: $WEB_PORT"
echo "Auto-connect: $AUTO_CONNECT"
echo ""

read -p "Continue with installation? [Y/n]: " CONFIRM
CONFIRM=${CONFIRM:-Y}

if [[ ! $CONFIRM =~ ^[Yy]$ ]]; then
    echo "Installation cancelled."
    exit 0
fi

echo ""
echo "🔧 Starting installation..."
echo ""

# Step 1: Add user to dialout group
echo "1️⃣  Adding user '$ACTUAL_USER' to dialout group..."
usermod -a -G dialout $ACTUAL_USER
echo "✓ User added to dialout group"
echo ""

# Step 2: Ensure Python dependencies are installed
echo "2️⃣  Checking Python virtual environment..."
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    echo "Creating virtual environment..."
    sudo -u $ACTUAL_USER python3 -m venv "$SCRIPT_DIR/venv"
fi

echo "Installing/updating dependencies..."
sudo -u $ACTUAL_USER "$SCRIPT_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u $ACTUAL_USER "$SCRIPT_DIR/venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" -q
echo "✓ Python dependencies installed"
echo ""

# Step 3: Create systemd service file
echo "3️⃣  Creating systemd service..."

# Determine home directory
HOME_DIR=$(eval echo ~$ACTUAL_USER)

# Build command arguments
CMD_ARGS="--host 0.0.0.0 --port $WEB_PORT --serial-port $SERIAL_PORT --baudrate $BAUD_RATE"
if [[ $AUTO_CONNECT =~ ^[Yy]$ ]]; then
    CMD_ARGS="$CMD_ARGS --auto-connect"
fi

# Create service file
cat > /etc/systemd/system/tascam-controller.service <<EOF
[Unit]
Description=TASCAM CD-400U Web Controller
After=network.target

[Service]
Type=simple
User=$ACTUAL_USER
WorkingDirectory=$SCRIPT_DIR
Environment="PATH=$SCRIPT_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/app.py $CMD_ARGS
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "✓ Service file created at /etc/systemd/system/tascam-controller.service"
echo ""

# Step 4: Reload systemd and enable service
echo "4️⃣  Enabling service to start on boot..."
systemctl daemon-reload
systemctl enable tascam-controller.service
echo "✓ Service enabled"
echo ""

# Step 5: Start the service now
echo "5️⃣  Starting service..."
systemctl start tascam-controller.service

# Wait a moment for service to start
sleep 2

# Check service status
if systemctl is-active --quiet tascam-controller.service; then
    echo "✓ Service started successfully"
else
    echo "⚠️  Service may have failed to start. Checking status..."
    systemctl status tascam-controller.service --no-pager
fi

echo ""
echo "=============================================="
echo "✅ Installation Complete!"
echo "=============================================="
echo ""
echo "Service Details:"
echo "  Name: tascam-controller.service"
echo "  Status: $(systemctl is-active tascam-controller.service)"
echo "  Enabled: $(systemctl is-enabled tascam-controller.service)"
echo ""
echo "Web Interface:"
echo "  URL: http://$(hostname -I | awk '{print $1}'):$WEB_PORT"
echo "  Local: http://localhost:$WEB_PORT"
echo ""
echo "Useful Commands:"
echo "  View logs:    sudo journalctl -u tascam-controller -f"
echo "  Stop service: sudo systemctl stop tascam-controller"
echo "  Restart:      sudo systemctl restart tascam-controller"
echo "  Disable boot: sudo systemctl disable tascam-controller"
echo "  Check status: sudo systemctl status tascam-controller"
echo ""
echo "⚠️  IMPORTANT: You must log out and log back in (or reboot)"
echo "   for serial port permissions to take effect."
echo ""
echo "The service will automatically start on every boot."
echo ""
