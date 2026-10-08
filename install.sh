#!/bin/bash

# TASCAM CD-400U Web Controller - Installation Script
# For Raspberry Pi 3 or later

set -e

echo "======================================"
echo "TASCAM CD-400U Controller Installation"
echo "======================================"
echo ""

# Check if running on Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo "❌ This script is designed for Linux (Raspberry Pi OS)"
    exit 1
fi

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "❌ Please do not run as root. Run as normal user (pi)."
    exit 1
fi

# Update system
echo "📦 Updating system packages..."
sudo apt update

# Install dependencies
echo "📦 Installing system dependencies..."
sudo apt install -y python3 python3-pip python3-venv git

# Add user to dialout group
echo "🔧 Configuring serial port permissions..."
sudo usermod -a -G dialout $USER

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "🐍 Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate and install Python packages
echo "📦 Installing Python packages..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Find USB serial device
echo ""
echo "🔍 Checking for USB-RS232 adapter..."
if ls /dev/ttyUSB* 1> /dev/null 2>&1; then
    echo "✅ Found USB serial device(s):"
    ls -l /dev/ttyUSB*
else
    echo "⚠️  No /dev/ttyUSB* devices found."
    echo "   Please connect your USB-RS232 adapter and run:"
    echo "   ls -l /dev/ttyUSB*"
fi

echo ""
echo "======================================"
echo "✅ Installation Complete!"
echo "======================================"
echo ""
echo "Next steps:"
echo "1. Verify your USB-RS232 adapter is connected"
echo "2. Run: source venv/bin/activate"
echo "3. Run: python app.py --serial-port /dev/serial/by-id/<your adapter>"
echo "   (or: python app.py --sim  to try it without the deck)"
echo ""
echo "⚠️  IMPORTANT: You must log out and log back in for"
echo "   serial port permissions to take effect, or reboot:"
echo "   sudo reboot"
echo ""
echo "For system service installation, see README.md"
echo ""
