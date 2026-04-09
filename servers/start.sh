#!/usr/bin/env bash
# Sparkplug MCP Server — startup wrapper
# Installs deps silently on first run, then launches the server.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/.sparkplug-venv"

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
  # Windows venvs use Scripts/, Linux uses bin/
  if [ -d "$VENV_DIR/Scripts" ]; then
    "$VENV_DIR/Scripts/python.exe" -m pip install --upgrade pip
    "$VENV_DIR/Scripts/python.exe" -m pip install -r "$SCRIPT_DIR/requirements.txt"
  else
    "$VENV_DIR/bin/python" -m pip install -q --upgrade pip
    "$VENV_DIR/bin/python" -m pip install -q -r "$SCRIPT_DIR/requirements.txt"
  fi
fi

# Launch server with correct Python path
if [ -f "$VENV_DIR/Scripts/python.exe" ]; then
  exec "$VENV_DIR/Scripts/python.exe" "$SCRIPT_DIR/server.py"
else
  exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/server.py"
fi
