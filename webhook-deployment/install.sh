#!/bin/bash
# Installation script for webhook deployment service

set -e

echo "Installing GitHub Webhook Deployment Service..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (use sudo)"
  exit 1
fi

# Configuration
WEBHOOK_USER="matrixbot"
WEBHOOK_DIR="/home/matrixbot/pdf-bot/webhook-deployment"
SERVICE_NAME="matrix-pdf-bot-webhook"

# Install dependencies with uv
echo "Setting up Python environment with uv..."
cd "$WEBHOOK_DIR"
sudo -u "$WEBHOOK_USER" /home/matrixbot/.local/bin/uv sync

# Make webhook server executable
chmod +x webhook_server.py

# Create log file with proper permissions
touch /var/log/matrix-pdf-bot-webhook.log
chown "$WEBHOOK_USER:$WEBHOOK_USER" /var/log/matrix-pdf-bot-webhook.log

# Install systemd service
echo "Installing systemd service..."
cp matrix-pdf-bot-webhook.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# Add matrixbot user to sudoers for service restart (if not already present)
SUDOERS_LINE="$WEBHOOK_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart matrix-pdf-bot"
if ! grep -q "$SUDOERS_LINE" /etc/sudoers; then
  echo "Adding sudo permissions for service restart..."
  echo "$SUDOERS_LINE" >>/etc/sudoers
fi

echo ""
echo "Installation completed!"
echo ""
echo "Next steps:"
echo "1. Copy .env.example to .env and configure:"
echo "   cp .env.example .env"
echo "   nano .env"
echo ""
echo "2. Generate webhook secret:"
echo "   openssl rand -hex 32"
echo ""
echo "3. Start the service:"
echo "   systemctl start $SERVICE_NAME"
echo ""
echo "4. Check service status:"
echo "   systemctl status $SERVICE_NAME"
echo ""
echo "5. View logs:"
echo "   journalctl -u $SERVICE_NAME -f"

