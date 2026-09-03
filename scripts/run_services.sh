#!/bin/bash

# run_services.sh
# ExecStart target for the edge-tracker systemd service. Runs main.py (camera +
# detection) and bridge.py (scale MQTT bridge) as sibling processes under one
# unit, without merging their code — if either one dies, both are torn down so
# systemd's Restart=always brings the pair back up together.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
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
