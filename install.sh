#!/usr/bin/env bash
# CarterPCs Monitor installer for Raspberry Pi OS / Debian / Ubuntu.
# Usage: curl -fsSL https://raw.githubusercontent.com/ZipperedJon/carterpcs-monitor/main/install.sh | bash
set -euo pipefail

REPO_URL="${CARTERPCS_REPO:-https://github.com/ZipperedJon/carterpcs-monitor.git}"
BRANCH="${CARTERPCS_BRANCH:-main}"
INSTALL_DIR="${CARTERPCS_DIR:-$HOME/carterpcs-monitor}"
PORT="${CARTERPCS_PORT:-8080}"
SERVICE="carterpcs-monitor"
RUN_USER="$(id -un)"

echo "==> Installing CarterPCs Monitor into $INSTALL_DIR"

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "==> Installing system packages (git, python3)"
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq git python3 python3-venv python3-pip >/dev/null

if [ -d "$INSTALL_DIR/.git" ]; then
  echo "==> Existing install found, updating"
  git -C "$INSTALL_DIR" pull --ff-only
else
  git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

echo "==> Setting up Python environment"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

echo "==> Creating systemd service"
$SUDO tee "/etc/systemd/system/$SERVICE.service" >/dev/null <<EOF
[Unit]
Description=CarterPCs Monitor
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$INSTALL_DIR
Environment=PORT=$PORT
Environment=PYTHONUNBUFFERED=1
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

$SUDO systemctl daemon-reload
$SUDO systemctl enable --now "$SERVICE" >/dev/null 2>&1
$SUDO systemctl restart "$SERVICE"

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "✅ CarterPCs Monitor is running!"
echo "   Open http://${IP:-localhost}:$PORT in your browser"
echo "   Logs:      journalctl -u $SERVICE -f"
echo "   Uninstall: bash $INSTALL_DIR/uninstall.sh"
