#!/bin/bash
# PodPing Watcher - Uninstall Script
# Cleanly removes the PodPing watcher service

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
SERVICE_NAME="podping-watcher"
SERVICE_USER="podping"
INSTALL_DIR="/opt/podping-watcher"

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }

# Check root
if [[ $EUID -ne 0 ]]; then
   log_error "This script must be run as root (use sudo)"
   exit 1
fi

echo "======================================"
echo "PodPing Watcher Uninstaller"
echo "======================================"
echo ""
echo "This will remove:"
echo "  - Systemd service: $SERVICE_NAME"
echo "  - Service user: $SERVICE_USER"
echo "  - Installation directory: $INSTALL_DIR"
echo ""
read -p "Are you sure? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_info "Uninstall cancelled"
    exit 0
fi

# Step 1: Stop and disable service
if systemctl list-units --full -all | grep -q "$SERVICE_NAME.service"; then
    log_info "Stopping service..."
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
fi

# Step 2: Remove systemd service file
if [ -f "/etc/systemd/system/$SERVICE_NAME.service" ]; then
    log_info "Removing systemd service..."
    rm -f "/etc/systemd/system/$SERVICE_NAME.service"
    systemctl daemon-reload
fi

# Step 3: Remove installation directory
if [ -d "$INSTALL_DIR" ]; then
    log_info "Removing installation directory..."
    rm -rf "$INSTALL_DIR"
fi

# Step 4: Remove user (optional)
if id "$SERVICE_USER" &>/dev/null; then
    read -p "Remove service user '$SERVICE_USER'? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "Removing service user..."
        userdel "$SERVICE_USER" 2>/dev/null || true
    fi
fi

# Step 5: Clean up logs (optional)
read -p "Remove all logs? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    log_info "Cleaning up logs..."
    journalctl --vacuum-time=1s 2>/dev/null || true
fi

log_info "✅ Uninstall complete!"
echo ""
echo "PodPing Watcher has been removed from your system."
