#!/bin/bash
# PodPing Watcher Health Check Script

SERVICE="podping-watcher"
MAX_MEMORY=512  # MB

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "======================================"
echo "PodPing Watcher Health Check"
echo "======================================"

# Check if service is running
if systemctl is-active --quiet $SERVICE; then
    echo -e "${GREEN}✓${NC} Service Status: Running"
    
    # Get PID and memory usage
    PID=$(systemctl show -p MainPID --value $SERVICE)
    if [ "$PID" != "0" ]; then
        MEMORY=$(ps -o rss= -p $PID 2>/dev/null | awk '{print int($1/1024)}')
        if [ -n "$MEMORY" ]; then
            echo -e "  Memory Usage: ${MEMORY}MB / ${MAX_MEMORY}MB"
            if [ "$MEMORY" -gt "$MAX_MEMORY" ]; then
                echo -e "${YELLOW}⚠${NC}  Warning: High memory usage"
            fi
        fi
    fi
    
    # Check for recent errors
    ERRORS=$(journalctl -u $SERVICE --since "1 hour ago" 2>/dev/null | grep -c ERROR)
    echo -e "  Errors (last hour): $ERRORS"
    
    # Show recent activity
    echo ""
    echo "Recent Activity (last 5 log entries):"
    echo "--------------------------------------"
    journalctl -u $SERVICE -n 5 --no-pager 2>/dev/null
    
    exit 0
else
    echo -e "${RED}✗${NC} Service Status: Not Running!"
    echo ""
    echo "Last 10 log entries:"
    echo "--------------------"
    journalctl -u $SERVICE -n 10 --no-pager 2>/dev/null
    
    echo ""
    echo "To start the service, run:"
    echo "  sudo systemctl start $SERVICE"
    
    exit 1
fi
