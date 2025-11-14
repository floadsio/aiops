#!/bin/bash
# Installation script for aiops systemd service
# Usage: sudo ./install-service.sh [USER] [INSTALL_DIR]

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_FILE="$SCRIPT_DIR/aiops.service"

# Default values
DEFAULT_USER="syseng"
DEFAULT_INSTALL_DIR="/home/syseng/aiops"

# Parse arguments
SERVICE_USER="${1:-$DEFAULT_USER}"
INSTALL_DIR="${2:-$DEFAULT_INSTALL_DIR}"
SERVICE_FILE="/etc/systemd/system/aiops.service"

echo "Installing aiops systemd service..."
echo "  User: $SERVICE_USER"
echo "  Installation directory: $INSTALL_DIR"
echo "  Service file: $SERVICE_FILE"
echo

# Verify template file exists
if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "Error: Template file not found at $TEMPLATE_FILE"
    exit 1
fi

# Verify user exists
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    echo "Error: User '$SERVICE_USER' does not exist"
    exit 1
fi

# Verify installation directory exists
if [ ! -d "$INSTALL_DIR" ]; then
    echo "Error: Installation directory '$INSTALL_DIR' does not exist"
    exit 1
fi

# Verify virtual environment exists
if [ ! -f "$INSTALL_DIR/.venv/bin/gunicorn" ]; then
    echo "Error: Virtual environment not found at $INSTALL_DIR/.venv"
    echo "Please run 'make sync' to create the virtual environment first"
    exit 1
fi

# Create logs directory if it doesn't exist
LOGS_DIR="$INSTALL_DIR/logs"
if [ ! -d "$LOGS_DIR" ]; then
    echo "Creating logs directory: $LOGS_DIR"
    mkdir -p "$LOGS_DIR"
    chown "$SERVICE_USER:$SERVICE_USER" "$LOGS_DIR"
fi

# Generate service file from template
echo "Generating service file..."
sed -e "s|User=syseng|User=$SERVICE_USER|g" \
    -e "s|Group=syseng|Group=$SERVICE_USER|g" \
    -e "s|WorkingDirectory=/home/syseng/aiops|WorkingDirectory=$INSTALL_DIR|g" \
    -e "s|/home/syseng/.local/bin:/home/syseng/aiops/.venv/bin|$HOME/.local/bin:$INSTALL_DIR/.venv/bin|g" \
    -e "s|/home/syseng/aiops|$INSTALL_DIR|g" \
    "$TEMPLATE_FILE" > "$SERVICE_FILE"

echo "Service file installed to $SERVICE_FILE"

# Reload systemd
echo "Reloading systemd daemon..."
systemctl daemon-reload

# Enable service
echo "Enabling aiops service..."
systemctl enable aiops.service

echo
echo "Installation complete!"
echo
echo "To start the service:"
echo "  sudo systemctl start aiops"
echo
echo "To check status:"
echo "  sudo systemctl status aiops"
echo
echo "To view logs:"
echo "  sudo journalctl -u aiops -f"
echo "  or: tail -f $LOGS_DIR/aiops.log"
