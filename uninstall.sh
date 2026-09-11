#!/usr/bin/env bash
#
# IndoGeek Pterodactyl Uninstaller - global entry point.
# Installs any missing runtime dependency (Python 3), prepares the project's
# state/log directories, and runs the interactive uninstaller.
#
# Usable from anywhere:
#   cd /some/dir && sudo /path/to/project/uninstall.sh
#
set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
PROJECT_DIR="$(dirname "$SCRIPT_PATH")"
PYTHON_BIN="python3"

ensure_python() {
  local missing=""
  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 \
     || ! "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    missing="python3"
  fi

  if [ -n "$missing" ]; then
    echo "[SETUP] Python 3 (3.8+) is required by the scripts and was not found."
    echo "[SETUP] Installing it with apt-get..."
    apt-get update >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 >/dev/null
  fi

  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 \
     || ! "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    echo "[SETUP] Python 3.8+ is still unavailable after the installation attempt." >&2
    exit 1
  fi
}

if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    echo "[SETUP] The uninstaller must run as root; re-running through sudo..."
    exec sudo "$SCRIPT_PATH" "$@"
  fi
  echo "[SETUP] Run this script as root (sudo is not available):" >&2
  echo "        sudo $SCRIPT_PATH" >&2
  exit 1
fi

ensure_python

mkdir -p "$PROJECT_DIR/state" "$PROJECT_DIR/logs"

echo "[SETUP] Starting IndoGeek Pterodactyl uninstaller..."
echo "[SETUP] Logs: $PROJECT_DIR/logs | State: $PROJECT_DIR/state"
exec "$PYTHON_BIN" "$PROJECT_DIR/uninstall.py" "$@"