#!/usr/bin/env bash
# Sets up this repo on a fresh Raspberry Pi clone and gets edge-tracker.service
# running: venv, deps, .env, systemd unit, enable + start.
#
# Usage: ./tools/setup.sh
# Re-run anytime — every step is idempotent (skips what's already done).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "==> Repo: $REPO_DIR"

# --- 1. Python venv + deps -------------------------------------------------
if [ ! -d venv ]; then
    echo "==> Creating venv"
    python3 -m venv venv
fi

echo "==> Installing Python dependencies"
venv/bin/pip install --quiet --upgrade pip
venv/bin/pip install --quiet -r requirements.txt

# --- 2. .env -----------------------------------------------------------
if [ ! -f .env ]; then
    echo "==> Creating .env from .env.example (edit it before starting the service)"
    cp .env.example .env
else
    echo "==> .env already exists, leaving it as-is"
fi

# --- 3. External tools needed for camera recording/upload ------------------
for bin in ffmpeg rclone; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "!! WARNING: '$bin' not found on PATH — required if RECORDING_ENABLED=true in .env"
    fi
done
if command -v rclone >/dev/null 2>&1; then
    if ! sudo rclone listremotes 2>/dev/null | grep -q .; then
        echo "!! WARNING: no rclone remotes configured for root — run 'sudo rclone config' to set up DRIVE_REMOTE"
    fi
fi

RECORDINGS_DIR="$(grep -E '^RECORDINGS_DIR=' .env | cut -d= -f2- || true)"
if [ -n "$RECORDINGS_DIR" ]; then
    sudo mkdir -p "$RECORDINGS_DIR"
fi

# --- 4. systemd unit ---------------------------------------------------
SERVICE_SRC="tools/systemd/edge-tracker.service"
SERVICE_DST="/etc/systemd/system/edge-tracker.service"

echo "==> Installing systemd unit -> $SERVICE_DST"
sudo cp "$SERVICE_SRC" "$SERVICE_DST"
sudo systemctl daemon-reload
sudo systemctl enable edge-tracker.service

echo "==> Restarting edge-tracker.service"
sudo systemctl restart edge-tracker.service

sleep 2
sudo systemctl status edge-tracker.service --no-pager || true

cat <<EOF

==> Done.
    Edit .env if you haven't already, then:
      sudo systemctl restart edge-tracker.service
    Tail logs with:
      journalctl -u edge-tracker.service -f
EOF
