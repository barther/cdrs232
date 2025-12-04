#!/usr/bin/env bash
set -e

### CONFIGURE THIS ###
REBOOT_TIME="03:00"  # 3:00 AM daily
######################

echo "=========================================="
echo " Daily Reboot Cron Job Setup"
echo "=========================================="
echo ""
echo "This will schedule a daily reboot at ${REBOOT_TIME}"
echo ""

if [ "$EUID" -ne 0 ]; then
  echo "Please run this script with sudo:"
  echo "  sudo $0"
  exit 1
fi

# Parse hour and minute from REBOOT_TIME
HOUR=$(echo $REBOOT_TIME | cut -d: -f1)
MINUTE=$(echo $REBOOT_TIME | cut -d: -f2)

# Create cron job entry
CRON_ENTRY="${MINUTE} ${HOUR} * * * /sbin/reboot"

echo "==> Checking for existing reboot cron job..."
# Remove any existing reboot cron jobs for root
crontab -l 2>/dev/null | grep -v "/sbin/reboot" | crontab - || true

echo "==> Adding new daily reboot cron job..."
# Add the new cron job
(crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -

echo "==> Verifying cron job..."
echo ""
echo "Current cron jobs for root:"
crontab -l | grep reboot
echo ""

echo "=========================================="
echo " Daily Reboot Setup Complete!"
echo "=========================================="
echo ""
echo "The Pi will now reboot daily at ${REBOOT_TIME}."
echo ""
echo "This ensures:"
echo "  - Fresh system state every day"
echo "  - Clears any memory leaks or hung processes"
echo "  - Services restart cleanly"
echo ""
echo "To change the time, edit REBOOT_TIME at the top"
echo "of this script and run it again."
echo ""
echo "To remove the cron job:"
echo "  sudo crontab -e"
echo "  (then delete the line with '/sbin/reboot')"
echo ""
echo "Next reboot: Tomorrow at ${REBOOT_TIME}"
echo "=========================================="
