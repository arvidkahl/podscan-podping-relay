#!/bin/bash
# PodPing Watcher - Quick Deployment Script for Podscan.fm
# Compatible with Ubuntu 22/24
# Usage: sudo bash install.sh <TARGET_URL>

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
TARGET_URL="${1:-http://localhost:8080/-/podping}"
INSTALL_DIR="/opt/podping-watcher"
SERVICE_USER="podping"
SERVICE_NAME="podping-watcher"

# Functions
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }

# Check root
if [[ $EUID -ne 0 ]]; then
   log_error "This script must be run as root (use sudo)"
   exit 1
fi

log_info "🚀 PodPing Watcher Quick Installer"
log_info "Target URL: $TARGET_URL"

# Step 1: Install dependencies
log_info "Installing system dependencies..."
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv curl > /dev/null 2>&1

# Step 2: Create service user
log_info "Setting up service user..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -s /bin/false -m -d "$INSTALL_DIR" "$SERVICE_USER"
fi

# Step 3: Setup directory
log_info "Creating installation directory..."
mkdir -p "$INSTALL_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# Step 4: Copy watcher script
log_info "Installing watcher script..."
if [ -f "watcher.py" ]; then
    cp watcher.py "$INSTALL_DIR/"
else
    log_error "watcher.py not found in current directory!"
    exit 1
fi

# Step 5: Setup Python environment
log_info "Setting up Python environment..."
sudo -u "$SERVICE_USER" bash << EOF
cd "$INSTALL_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip > /dev/null 2>&1
pip install beem requests > /dev/null 2>&1
EOF

# Step 6: Create configuration
log_info "Creating configuration..."
cat > "$INSTALL_DIR/config.env" << ENV_CONFIG
# PodPing Watcher Configuration
TARGET_URL=$TARGET_URL
BATCH_SIZE=50
BATCH_TIMEOUT=3
LOOKBACK_MINUTES=5
DEDUPE_WINDOW=30
LOG_LEVEL=INFO
ENV_CONFIG

chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/config.env"

# Step 7: Create systemd service
log_info "Creating systemd service..."
cat > "/etc/systemd/system/$SERVICE_NAME.service" << 'SYSTEMD_SERVICE'
[Unit]
Description=PodPing Watcher for Podscan.fm
Documentation=https://github.com/Podcastindex-org/podping
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=podping
Group=podping
WorkingDirectory=/opt/podping-watcher
EnvironmentFile=/opt/podping-watcher/config.env
ExecStart=/opt/podping-watcher/venv/bin/python /opt/podping-watcher/watcher.py

# Restart configuration
Restart=always
RestartSec=10
StartLimitInterval=300
StartLimitBurst=5

# Resource limits
MemoryLimit=512M
CPUQuota=50%

# Security
PrivateTmp=yes
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/podping-watcher

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=podping-watcher

[Install]
WantedBy=multi-user.target
SYSTEMD_SERVICE

# Step 8: Start service
log_info "Starting service..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl start "$SERVICE_NAME"

sleep 2

# Step 9: Verify
if systemctl is-active --quiet "$SERVICE_NAME"; then
    log_info "✅ Service is running successfully!"
    
    echo ""
    echo "=== Service Status ==="
    systemctl status "$SERVICE_NAME" --no-pager | head -n 10
    
    echo ""
    echo "=== Commands ==="
    echo "View logs:    journalctl -u $SERVICE_NAME -f"
    echo "Restart:      systemctl restart $SERVICE_NAME"
    echo "Stop:         systemctl stop $SERVICE_NAME"
    echo "Status:       systemctl status $SERVICE_NAME"
    echo ""
    log_info "🎉 Installation complete!"
else
    log_error "Service failed to start!"
    journalctl -u "$SERVICE_NAME" -n 20 --no-pager
    exit 1
fi
