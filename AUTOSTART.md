# Auto-Start Configuration

This guide will help you configure the TASCAM controller to run automatically when your Raspberry Pi boots.

## Quick Setup

Run the auto-start setup script:

```bash
sudo ./setup-autostart.sh
```

The script will prompt you for:
- **Serial port** (default: /dev/ttyUSB0)
- **Baud rate** (default: 9600)
- **Web server port** (default: 5000)
- **Auto-connect** on startup (default: Yes)

That's it! The service will be installed and started automatically.

## What the Script Does

1. ✅ Adds your user to the `dialout` group (for serial port access)
2. ✅ Creates/updates Python virtual environment
3. ✅ Installs all required Python packages
4. ✅ Creates systemd service configuration
5. ✅ Enables service to start on boot
6. ✅ Starts the service immediately

## After Installation

### Access the Web Interface

From any device on your network:
```
http://<your-pi-ip>:5000
```

Find your Pi's IP with:
```bash
hostname -I
```

### Managing the Service

**View live logs:**
```bash
sudo journalctl -u tascam-controller -f
```

**Check service status:**
```bash
sudo systemctl status tascam-controller
```

**Stop the service:**
```bash
sudo systemctl stop tascam-controller
```

**Start the service:**
```bash
sudo systemctl start tascam-controller
```

**Restart the service:**
```bash
sudo systemctl restart tascam-controller
```

**Disable auto-start on boot:**
```bash
sudo systemctl disable tascam-controller
```

**Enable auto-start on boot:**
```bash
sudo systemctl enable tascam-controller
```

## Manual Configuration

If you prefer manual setup or need to change settings later:

### Edit Service File

```bash
sudo nano /etc/systemd/system/tascam-controller.service
```

Change the `ExecStart` line to modify settings:
```
ExecStart=/home/pi/cdrs232/venv/bin/python /home/pi/cdrs232/app.py \
    --host 0.0.0.0 \
    --port 5000 \
    --serial-port /dev/ttyUSB0 \
    --baudrate 9600 \
    --auto-connect
```

After editing, reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart tascam-controller
```

### Available Command Line Options

- `--host <ip>` - Host to bind to (default: 0.0.0.0 for all interfaces)
- `--port <port>` - Web server port (default: 5000)
- `--serial-port <port>` - Serial device (default: /dev/ttyUSB0)
- `--baudrate <rate>` - Baud rate: 4800, 9600, 19200, 38400, 57600
- `--auto-connect` - Connect to device automatically on startup

## Troubleshooting

### Service won't start

Check the logs:
```bash
sudo journalctl -u tascam-controller -n 50
```

Common issues:
1. **Serial port not found** - Check USB adapter is connected: `ls -l /dev/ttyUSB*`
2. **Permission denied** - Reboot after running setup (dialout group needs session restart)
3. **Port already in use** - Change web port in service file
4. **Python packages missing** - Reinstall: `./install.sh`

### Can't access web interface

1. **Check service is running:**
   ```bash
   sudo systemctl status tascam-controller
   ```

2. **Check firewall** (if enabled):
   ```bash
   sudo ufw allow 5000/tcp
   ```

3. **Test locally first:**
   ```bash
   curl http://localhost:5000
   ```

4. **Verify Pi's IP address:**
   ```bash
   hostname -I
   ```

### Serial port permissions

If you get "Permission denied" for serial port:

```bash
# Add user to dialout group
sudo usermod -a -G dialout $USER

# Verify group membership
groups $USER

# Reboot to apply
sudo reboot
```

### Change serial port device

If your USB adapter appears as a different device (e.g., `/dev/ttyAMA0`):

```bash
# Find your device
ls -l /dev/tty*

# Update service file
sudo nano /etc/systemd/system/tascam-controller.service

# Change the --serial-port argument
# Then reload and restart
sudo systemctl daemon-reload
sudo systemctl restart tascam-controller
```

## Uninstall

To remove the auto-start service:

```bash
# Stop and disable service
sudo systemctl stop tascam-controller
sudo systemctl disable tascam-controller

# Remove service file
sudo rm /etc/systemd/system/tascam-controller.service

# Reload systemd
sudo systemctl daemon-reload
```

The application files remain in place - only auto-start is removed.

## Network Configuration Tips

### Set Static IP (Recommended)

Edit DHCP config:
```bash
sudo nano /etc/dhcpcd.conf
```

Add at the end (adjust for your network):
```
interface eth0
static ip_address=192.168.1.100/24
static routers=192.168.1.1
static domain_name_servers=192.168.1.1 8.8.8.8
```

For WiFi, use `interface wlan0` instead.

Restart networking:
```bash
sudo systemctl restart dhcpcd
```

### Access via Hostname

Instead of IP address, you can use:
```
http://raspberrypi.local:5000
```

(Default hostname is `raspberrypi`, change in `/etc/hostname`)

## Performance Tips

### Running on Raspberry Pi Zero

For Pi Zero/Zero W (lower RAM), consider:

1. Disable unused services
2. Use lite OS image
3. Limit browser tabs when accessing interface

### Running 24/7

For always-on operation:

1. Use official Raspberry Pi power supply
2. Ensure good ventilation
3. Monitor logs occasionally: `sudo journalctl -u tascam-controller --since today`

## Advanced: Multiple TASCAM Devices

To run multiple controllers (different devices):

1. Create separate service files:
   - `tascam-controller-1.service`
   - `tascam-controller-2.service`

2. Use different ports and serial devices:
   ```
   # Service 1
   ExecStart=... --port 5000 --serial-port /dev/ttyUSB0

   # Service 2
   ExecStart=... --port 5001 --serial-port /dev/ttyUSB1
   ```

3. Enable both services

## Support

For issues:
1. Check logs: `sudo journalctl -u tascam-controller -f`
2. Verify hardware: `ls -l /dev/ttyUSB*`
3. Test manually: `python app.py --serial-port /dev/ttyUSB0`
4. Check this repository's issues on GitHub
