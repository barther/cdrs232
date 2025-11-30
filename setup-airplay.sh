#!/usr/bin/env bash
set -e

### CONFIGURE THESE ###
AIRPLAY_NAME="Church Sound System"
#######################

echo "=========================================="
echo " AirPlay Receiver Setup for Raspberry Pi"
echo "=========================================="
echo ""
echo "This will install shairport-sync to receive"
echo "AirPlay audio and output to 3.5mm jack."
echo ""
echo "AirPlay name: ${AIRPLAY_NAME}"
echo ""

if [ "$EUID" -ne 0 ]; then
  echo "Please run this script with sudo:"
  echo "  sudo $0"
  exit 1
fi

echo "==> Installing dependencies..."
apt update
apt install -y \
    build-essential \
    git \
    autoconf \
    automake \
    libtool \
    libpopt-dev \
    libconfig-dev \
    libasound2-dev \
    avahi-daemon \
    libavahi-client-dev \
    libssl-dev \
    libsoxr-dev \
    libplist-dev \
    libsodium-dev \
    libavutil-dev \
    libavcodec-dev \
    libavformat-dev \
    uuid-dev \
    libgcrypt-dev \
    xxd

echo "==> Checking if shairport-sync is already installed..."
if command -v shairport-sync &> /dev/null; then
    echo "shairport-sync is already installed. Skipping build."
else
    echo "==> Building shairport-sync from source..."
    cd /tmp

    # Remove old build if exists
    rm -rf shairport-sync

    # Clone and build
    git clone https://github.com/mikebrady/shairport-sync.git
    cd shairport-sync

    autoreconf -fi
    ./configure --sysconfdir=/etc \
                --with-alsa \
                --with-soxr \
                --with-avahi \
                --with-ssl=openssl \
                --with-systemd \
                --with-metadata

    make -j4
    make install

    echo "==> Cleaning up build files..."
    cd /tmp
    rm -rf shairport-sync
fi

echo "==> Configuring shairport-sync..."
cat > /etc/shairport-sync.conf <<EOF
// Configuration file for shairport-sync
// Church Sound System AirPlay Receiver

general = {
    name = "${AIRPLAY_NAME}";
    interpolation = "soxr";
    output_backend = "alsa";
    volume_range_db = 60;
    regtype = "_raop._tcp";
};

alsa = {
    output_device = "hw:0,0";  // Default audio output (3.5mm jack)
    mixer_control_name = "PCM";
    mixer_device = "hw:0";
};

sessioncontrol = {
    session_timeout = 20;
};

metadata = {
    enabled = "yes";
    include_cover_art = "no";
};
EOF

echo "==> Setting audio output to 3.5mm jack..."
# Force audio to 3.5mm headphone jack (not HDMI)
amixer cset numid=3 1 2>/dev/null || true

echo "==> Enabling and starting shairport-sync service..."
systemctl enable shairport-sync
systemctl restart shairport-sync

echo "==> Checking service status..."
sleep 2
if systemctl is-active --quiet shairport-sync; then
    echo "✓ shairport-sync is running!"
else
    echo "✗ Service failed to start. Check logs with:"
    echo "  sudo journalctl -u shairport-sync -n 50"
    exit 1
fi

echo ""
echo "=========================================="
echo " AirPlay Setup Complete!"
echo "=========================================="
echo ""
echo "Your Pi is now an AirPlay receiver named:"
echo "  \"${AIRPLAY_NAME}\""
echo ""
echo "To use:"
echo "1. Connect 3.5mm cable from Pi headphone jack to CD-400U AUX input"
echo "2. Switch CD-400U to AUX source"
echo "3. On your iPhone/iPad/Mac:"
echo "   - Open Control Center"
echo "   - Tap AirPlay icon"
echo "   - Select \"${AIRPLAY_NAME}\""
echo "   - Play music from any app!"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status shairport-sync   # Check status"
echo "  sudo systemctl restart shairport-sync  # Restart service"
echo "  sudo journalctl -u shairport-sync -f   # View logs"
echo ""
echo "To change the name, edit AIRPLAY_NAME at the top of this script"
echo "and run it again."
echo ""
echo "Enjoy! 🎵"
echo "=========================================="
