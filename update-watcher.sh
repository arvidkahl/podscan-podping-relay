#!/bin/bash
# Quick update script for podping-watcher
# Usage: sudo bash update-watcher.sh

set -e

# Configuration
INSTALL_DIR="/opt/podping-watcher"
SERVICE_NAME="podping-watcher"

# Check root
if [[ $EUID -ne 0 ]]; then
   echo "[ERROR] This script must be run as root (use sudo)"
   exit 1
fi

echo "[INFO] Stopping service..."
systemctl stop "$SERVICE_NAME"

echo "[INFO] Copying updated watcher.py..."
if [ -f "watcher.py" ]; then
    cp watcher.py "$INSTALL_DIR/"
    chown podping:podping "$INSTALL_DIR/watcher.py"
    echo "[INFO] ✓ Updated watcher.py"
else
    echo "[ERROR] watcher.py not found in current directory!"
    exit 1
fi

echo "[INFO] Starting service..."
systemctl start "$SERVICE_NAME"

sleep 2

echo "[INFO] Service status:"
systemctl status "$SERVICE_NAME" --no-pager -l | head -n 15

echo ""
echo "[INFO] ✅ Update complete! Watch logs with: journalctl -u $SERVICE_NAME -f"
