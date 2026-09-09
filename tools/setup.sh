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
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "!! WARNING: 'ffmpeg' not found on PATH — required if RECORDING_ENABLED=true in .env"
fi

if ! command -v rclone >/dev/null 2>&1; then
    echo "==> Installing rclone"
    curl -sSf https://rclone.org/install.sh | sudo bash
fi
if command -v rclone >/dev/null 2>&1; then
    if ! sudo rclone listremotes 2>/dev/null | grep -q .; then
        echo "!! WARNING: no rclone remotes configured for root — run 'sudo rclone config' to set up DRIVE_REMOTE"
    fi
fi

RECORDINGS_DIR="$(grep -E '^RECORDINGS_DIR=' .env | cut -d= -f2- || true)"
if [ -n "$RECORDINGS_DIR" ]; then
    sudo mkdir -p "$RECORDINGS_DIR"
fi

# --- 3b. zrok / OpenZiti tunnel ---------------------------------------------
if ! command -v zrok2 >/dev/null 2>&1 && ! command -v zrok >/dev/null 2>&1; then
    echo "==> Installing zrok (OpenZiti)"
    curl -sSf get.openziti.io/install.bash | sudo bash -s zrok2
else
    echo "==> zrok already installed, skipping"
fi

if ! grep -q "alias zrok='zrok2'" ~/.bashrc 2>/dev/null; then
    echo "==> Adding 'zrok' alias for zrok2 to ~/.bashrc"
    echo "alias zrok='zrok2'" >> ~/.bashrc
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

    Don't forget to add your .env and rclone.conf files to this device —
    they aren't part of the repo and won't come from git.

    Run 'source ~/.bashrc' (or open a new shell) to pick up the 'zrok' alias.
EOF
