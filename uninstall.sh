#!/usr/bin/env bash
# Removes the CarterPCs Monitor service and install folder (including your settings).
set -euo pipefail
INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

$SUDO systemctl disable --now carterpcs-monitor 2>/dev/null || true
$SUDO rm -f /etc/systemd/system/carterpcs-monitor.service
$SUDO systemctl daemon-reload
rm -rf "$INSTALL_DIR"
echo "CarterPCs Monitor removed."
