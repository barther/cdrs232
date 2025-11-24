# USB Serial Port Configuration Guide

## The Problem with `/dev/ttyUSB0`

The `/dev/ttyUSB0` device name **can change** in these situations:
- Multiple USB serial devices are connected
- Device is unplugged and replugged
- Different USB port is used
- System reboots with different device enumeration order

This can cause the controller to fail connecting after a reboot or when multiple USB devices are present.

## Recommended Solutions

### Option 1: Use by-id (Recommended)

The `/dev/serial/by-id/` path uses the device's serial number and won't change:

```bash
# Find your USB-RS232 adapter's persistent name
ls -l /dev/serial/by-id/

# Example output:
# usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0 -> ../../ttyUSB0
```

Update your connection settings to use the full path:
```bash
# Instead of:
--serial-port /dev/ttyUSB0

# Use:
--serial-port /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0
```

### Option 2: Use by-path (If You Always Use the Same USB Port)

The `/dev/serial/by-path/` path is based on physical USB port location:

```bash
# Find the path
ls -l /dev/serial/by-path/

# Example output:
# platform-3f980000.usb-usb-0:1.3:1.0-port0 -> ../../ttyUSB0
```

**Note**: This only works if you always plug into the same USB port.

### Option 3: Create a udev Rule (Advanced)

Create a custom device name that never changes:

1. Get device info:
   ```bash
   udevadm info --name=/dev/ttyUSB0 --attribute-walk | grep -E 'ATTRS{serial}|ATTRS{idVendor}|ATTRS{idProduct}'
   ```

2. Create udev rule:
   ```bash
   sudo nano /etc/udev/rules.d/99-tascam-serial.rules
   ```

3. Add rule (adjust serial number to match your device):
   ```
   SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="A50285BI", SYMLINK+="tascam0"
   ```

4. Reload rules:
   ```bash
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   ```

5. Use the new name:
   ```bash
   --serial-port /dev/tascam0
   ```

## Testing Your Configuration

After changing the serial port path:

```bash
# Test the connection
python app.py --serial-port /dev/serial/by-id/YOUR-DEVICE-NAME --baudrate 9600

# If it works, update your systemd service
sudo nano /etc/systemd/system/tascam-controller.service

# Change the ExecStart line to use the new port
# Then reload and restart
sudo systemctl daemon-reload
sudo systemctl restart tascam-controller
```

## Troubleshooting

**Can't find `/dev/serial/by-id/` directory:**
```bash
# The directory only exists if USB serial devices are connected
# Check if your device is recognized
lsusb
dmesg | grep tty
```

**Permission denied:**
```bash
# Verify user is in dialout group
groups $USER

# If not, add and reboot
sudo usermod -a -G dialout $USER
sudo reboot
```

**Device name still changes:**
- Use by-id (most reliable)
- Create udev rule (permanent custom name)
- Avoid unplugging/replugging the USB adapter

## Recommended Setup for Church Deployment

For maximum reliability in a church environment:

1. **Use by-id path** in the service configuration
2. **Label the USB port** physically so it's always plugged into the same port
3. **Cable tie the USB cable** to prevent accidental disconnection
4. **Document the port name** in `/etc/tascam-controller.conf` for reference

Example service configuration:
```ini
ExecStart=/home/pi/cdrs232/venv/bin/python /home/pi/cdrs232/app.py \
    --host 0.0.0.0 \
    --port 5000 \
    --serial-port /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0 \
    --baudrate 9600 \
    --auto-connect
```

This ensures the controller always finds the correct device, even after reboots or power cycles.
