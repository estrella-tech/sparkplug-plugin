#!/usr/bin/env bash
# Sparkplug MCP Server — startup wrapper
# Installs deps on first run (or when requirements.txt changes), then launches the server.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/.sparkplug-venv"
REQ_FILE="$SCRIPT_DIR/requirements.txt"
STAMP_FILE="$VENV_DIR/.req-stamp"

# Detect Python command
PYTHON_CMD=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    PYTHON_CMD="$cmd"
    break
  fi
done
if [ -z "$PYTHON_CMD" ]; then
  echo "ERROR: No python3 or python found in PATH" >&2
  exit 1
fi

# Detect venv bin directory (Scripts/ on Windows, bin/ on Linux/macOS)
venv_bin() {
  if [ -d "$VENV_DIR/Scripts" ]; then
    echo "$VENV_DIR/Scripts"
  else
    echo "$VENV_DIR/bin"
  fi
}

# Create venv if missing or broken (no python executable)
NEEDS_VENV=false
if [ ! -d "$VENV_DIR" ]; then
  NEEDS_VENV=true
elif [ ! -f "$VENV_DIR/Scripts/python.exe" ] && [ ! -f "$VENV_DIR/bin/python" ]; then
  echo "Venv appears broken, recreating..." >&2
  rm -rf "$VENV_DIR"
  NEEDS_VENV=true
fi

if [ "$NEEDS_VENV" = true ]; then
  "$PYTHON_CMD" -m venv "$VENV_DIR"
fi

VENV_PYTHON="$(venv_bin)/python"
[ -f "$(venv_bin)/python.exe" ] && VENV_PYTHON="$(venv_bin)/python.exe"

# Install/update deps if requirements.txt is newer than our stamp
if [ ! -f "$STAMP_FILE" ] || [ "$REQ_FILE" -nt "$STAMP_FILE" ]; then
  "$VENV_PYTHON" -m pip install --upgrade pip 2>/dev/null || true
  "$VENV_PYTHON" -m pip install -r "$REQ_FILE"
  touch "$STAMP_FILE"
fi

exec "$VENV_PYTHON" "$SCRIPT_DIR/server.py"
