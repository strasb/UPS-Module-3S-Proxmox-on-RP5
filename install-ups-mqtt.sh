#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/root/UPS-Module-3S-Proxmox-on-RP5"
SERVICE_SRC="$REPO_DIR/ups-mqtt.service"
SERVICE_DST="/etc/systemd/system/ups-mqtt.service"
ENV_EXAMPLE_SRC="$REPO_DIR/.env.ups-mqtt.example"
ENV_DST="/etc/default/ups-mqtt"

if [[ ! -d "$REPO_DIR" ]]; then
  echo "Repository directory not found: $REPO_DIR" >&2
  exit 1
fi

cd "$REPO_DIR"

echo "==> Updating repository"
git pull

echo "==> Creating/updating virtual environment"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "==> Installing systemd service"
sudo cp "$SERVICE_SRC" "$SERVICE_DST"

if [[ ! -f "$ENV_DST" ]]; then
  echo "==> Installing MQTT environment file"
  sudo cp "$ENV_EXAMPLE_SRC" "$ENV_DST"
else
  echo "==> Keeping existing MQTT environment file: $ENV_DST"
fi

sudo chmod 600 "$ENV_DST"

echo "==> Reloading systemd"
sudo systemctl daemon-reload
sudo systemctl enable ups-mqtt.service
sudo systemctl restart ups-mqtt.service

echo
echo "==> ups-mqtt.service status"
sudo systemctl status ups-mqtt.service --no-pager || true

echo
echo "==> Recent logs"
sudo journalctl -u ups-mqtt.service -n 50 --no-pager || true

echo
echo "If needed, edit MQTT settings in: $ENV_DST"
echo "Then restart with: sudo systemctl restart ups-mqtt.service"
