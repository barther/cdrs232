#!/usr/bin/env bash
set -e

### CONFIGURE THESE IF NEEDED ###
APP_USER="bart"
APP_DIR="/home/bart/cdrs232"
VENV_DIR="${APP_DIR}/venv"
SERVICE_NAME="tascam-rs232.service"
PYTHON_BIN="python3"

# Serial port (using persistent by-id path)
SERIAL_PORT="/dev/serial/by-id/usb-FTDI_USB_Serial_Converter_FTEM3Y6M-if00-port0"
BAUDRATE="9600"
#################################

if [ "$EUID" -ne 0 ]; then
  echo "Please run this script with sudo:"
  echo "  sudo $0"
  exit 1
fi

echo "==> Installing system packages..."
apt update
apt install -y python3-venv python3-pip python3-serial

echo "==> Ensuring ${APP_USER} is in 'dialout' group for serial access..."
usermod -a -G dialout "${APP_USER}"

echo "==> Creating virtual environment at ${VENV_DIR} (if not already present)..."
sudo -u "${APP_USER}" bash -lc "
  cd '${APP_DIR}' && \
  if [ ! -d '${VENV_DIR}' ]; then
    ${PYTHON_BIN} -m venv venv
  fi
"

echo "==> Installing Python dependencies from requirements.txt..."
sudo -u "${APP_USER}" bash -lc "
  cd '${APP_DIR}' && \
  source venv/bin/activate && \
  pip install --upgrade pip && \
  pip install -r requirements.txt
"

echo "==> Creating systemd service: ${SERVICE_NAME}"

cat >/etc/systemd/system/${SERVICE_NAME} <<EOF
[Unit]
Description=TASCAM CD-400U RS-232 Web Controller
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1

# Start the web controller with auto-connect
ExecStart=${VENV_DIR}/bin/python ${APP_DIR}/app.py \\
    --host 0.0.0.0 \\
    --port 5000 \\
    --serial-port ${SERIAL_PORT} \\
    --baudrate ${BAUDRATE} \\
    --auto-connect

# Restart on failure with backoff
Restart=on-failure
RestartSec=10
StartLimitInterval=5min
StartLimitBurst=3

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=tascam-rs232

[Install]
WantedBy=multi-user.target
EOF

echo "==> Reloading systemd and enabling service..."
systemctl daemon-reload
systemctl enable ${SERVICE_NAME}

echo
echo "======================================================="
echo " Setup complete."
echo
echo " Service name : ${SERVICE_NAME}"
echo " App dir      : ${APP_DIR}"
echo " Venv         : ${VENV_DIR}"
echo " Serial port  : ${SERIAL_PORT}"
echo " Baudrate     : ${BAUDRATE}"
echo " Web UI       : http://YOUR_PI_IP:5000"
echo
echo "The service will start automatically on boot."
echo
echo "To start now:"
echo "  sudo systemctl start ${SERVICE_NAME}"
echo
echo "To check status:"
echo "  sudo systemctl status ${SERVICE_NAME}"
echo
echo "To view logs:"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
echo
echo "IMPORTANT: Reboot required for 'dialout' group changes."
echo "======================================================="
