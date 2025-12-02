#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMER_FILE="$SCRIPT_DIR/aiops-claude-update.timer"
SERVICE_FILE="$SCRIPT_DIR/aiops-claude-update.service"

echo "Installing Claude Code auto-update systemd timer..."

# Copy unit files to systemd directory
sudo cp "$TIMER_FILE" /etc/systemd/system/
sudo cp "$SERVICE_FILE" /etc/systemd/system/

# Set permissions
sudo chmod 644 /etc/systemd/system/aiops-claude-update.timer
sudo chmod 644 /etc/systemd/system/aiops-claude-update.service

# Reload systemd to pick up new units
sudo systemctl daemon-reload

# Enable and start the timer
sudo systemctl enable aiops-claude-update.timer
sudo systemctl start aiops-claude-update.timer

echo ""
echo "✓ Claude Code auto-update timer installed and started"
echo ""
echo "Check status:"
echo "  sudo systemctl status aiops-claude-update.timer"
echo ""
echo "View logs:"
echo "  sudo journalctl -u aiops-claude-update -f"
echo ""
echo "Next scheduled run:"
echo "  sudo systemctl list-timers aiops-claude-update.timer"
