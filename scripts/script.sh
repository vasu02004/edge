#!/bin/bash

# script.sh
#
# Two modes:
#   ./script.sh          (no args) — run as root, once, from a cloned copy of
#                         this repo, to take a fresh Pi from a clone to a
#                         running edge-tracker service: installs apt/system
#                         deps, creates a venv with both main.py's and
#                         bridge.py's requirements, installs the edge-tracker
#                         systemd service, and sets up log retention/cleanup.
#   ./script.sh run      — the systemd ExecStart target, invoked on every
#                         service start/restart: runs main.py (camera +
#                         detection) and bridge.py (scale MQTT bridge) as
#                         sibling processes, without merging their code. If
#                         either dies, both are torn down so systemd's
#                         Restart=always brings the pair back up together.
#                         Not meant to be run by hand.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

# ============================================================
# RUN MODE — the actual service entrypoint (kept minimal and
# fast: this runs on every restart, not just once at install).
# ============================================================
if [ "${1:-}" = "run" ]; then
  PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
  PYTHON="$PROJECT_DIR/venv/bin/python3"

  cd "$PROJECT_DIR"

  "$PYTHON" main.py --stream &
  MAIN_PID=$!

  "$PYTHON" bridge.py &
  BRIDGE_PID=$!

  cleanup() {
    kill "$MAIN_PID" "$BRIDGE_PID" 2>/dev/null
    wait "$MAIN_PID" "$BRIDGE_PID" 2>/dev/null
  }
  trap cleanup TERM INT

  # Whichever process exits first, tear down the other and exit non-zero so
  # systemd restarts the whole unit (both processes together).
  wait -n
  EXIT_CODE=$?
  cleanup
  exit "$EXIT_CODE"
fi

# ============================================================
# INSTALL MODE — one-time setup, run by hand as root.
# ============================================================
set -e

SERVICE_NAME="edge-tracker"

# Determine project directory: rely on script location first
if [ -f "$SCRIPT_DIR/main.py" ]; then
  PROJECT_DIR="$SCRIPT_DIR"
elif [ -f "$(dirname "$SCRIPT_DIR")/main.py" ]; then
  PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
elif [ -f "$PWD/main.py" ]; then
  PROJECT_DIR="$PWD"
elif [ -n "${SUDO_USER:-}" ]; then
  USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
  PROJECT_DIR="$USER_HOME/aurusguard-pi"
else
  USER_HOME=$HOME
  PROJECT_DIR="$USER_HOME/aurusguard-pi"
fi

# Verify the project directory exists and contains both main.py and bridge.py
if [ ! -d "$PROJECT_DIR" ] || [ ! -f "$PROJECT_DIR/main.py" ] || [ ! -f "$PROJECT_DIR/bridge.py" ]; then
  echo "Error: Could not locate project directory containing main.py and bridge.py."
  echo "Detected PROJECT_DIR=$PROJECT_DIR"
  exit 1
fi

if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo "Error: $PROJECT_DIR/.env not found."
  echo "Copy .env.example to .env and fill in the real values first."
  exit 1
fi

LOG_FILE="/var/log/install_edge_tracker.log"

exec > >(tee -a "$LOG_FILE")
exec 2>&1

echo "========================================="
echo "Installation started: $(date)"
echo "========================================="

if [[ "$EUID" -ne 0 ]]; then
  echo "This script must be run as root. Use sudo ./script.sh"
  exit 1
fi

if ! command -v apt >/dev/null 2>&1; then
  echo "apt is not available on this system. This script is intended for Debian/Ubuntu-based systems."
  exit 1
fi

echo "[1/9] Updating package lists..."
apt update

echo "[2/9] Installing Python3, venv, and system libs (opencv runtime + ffmpeg/rclone for camera recording)..."
apt install -y \
  python3 python3-venv python3-pip \
  libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
  ffmpeg rclone

echo "Python version: $(python3 -V)"

echo "[3/9] Creating venv and installing dependencies..."
cd "$PROJECT_DIR"
python3 -m venv venv
venv/bin/pip install --no-cache-dir --upgrade pip
venv/bin/pip install --no-cache-dir -r requirements.txt
venv/bin/pip install --no-cache-dir -r requirements-bridge.txt

echo "[4/9] Making script.sh executable..."
chmod +x "$PROJECT_DIR/scripts/script.sh"

echo "[5/9] Creating systemd service..."
cat >/etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Edge vault tracker (ArUco + open/close detection + camera recording/upload) and scale MQTT bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# This process now owns the camera device for both detection and recording
# (see camera/ffmpeg_capture.py) -- nothing else should open the camera while
# this runs. It also shells out to rclone to upload finished recordings, so
# \`rclone config\` must be set up for whichever user this runs as (root's
# rclone config here, since User=root below).
User=root
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/scripts/script.sh run
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Same Pi 4 (2GB) resource envelope as docker-compose.yml's cpus/mem_limit/
# pids_limit -- this native deployment has no Docker cgroup to enforce it
# otherwise, so a leak or runaway in either process is otherwise unbounded.
CPUQuota=400%
MemoryMax=1800M
MemorySwapMax=0
TasksMax=200

[Install]
WantedBy=multi-user.target
EOF

echo "[6/9] Enabling and starting service..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "[7/9] Configuring journald retention..."
mkdir -p /etc/systemd/journald.conf.d

cat >/etc/systemd/journald.conf.d/limits.conf <<EOF
[Journal]
SystemMaxUse=80M
MaxRetentionSec=14day
EOF

systemctl restart systemd-journald
journalctl --vacuum-size=80M
journalctl --vacuum-time=14d

echo "[8/9] Configuring log rotation for stats.csv..."
cat >/etc/logrotate.d/${SERVICE_NAME} <<EOF
$PROJECT_DIR/stats.csv {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    maxsize 80M
}
EOF

echo "[9/9] Creating weekly cleanup task..."
tee /etc/cron.weekly/pi-cleanup >/dev/null <<'EOF'
#!/bin/sh

apt-get clean
apt-get autoclean -y
apt-get autoremove -y

find /tmp -type f -mtime +7 -delete
find /var/tmp -type f -mtime +7 -delete

journalctl --vacuum-time=14d
journalctl --vacuum-size=80M
EOF

chmod +x /etc/cron.weekly/pi-cleanup

echo
echo "========================================="
echo "Installation completed successfully"
echo "========================================="
echo
echo "Installer log:"
echo "  $LOG_FILE"
echo
echo "Service status:"
systemctl --no-pager --full status "$SERVICE_NAME" || true

echo
echo "Useful commands:"
echo "  systemctl status $SERVICE_NAME"
echo "  systemctl restart $SERVICE_NAME"
echo "  journalctl -u $SERVICE_NAME -f"
echo
if ! rclone listremotes 2>/dev/null | grep -q .; then
  echo "NOTE: no rclone remotes configured yet. If RECORDING_ENABLED=true in .env,"
  echo "camera recordings won't upload until you run 'rclone config' as root and"
  echo "set up the remote named by DRIVE_REMOTE (default gdrive:)."
  echo
fi
echo "Completed at: $(date)"
