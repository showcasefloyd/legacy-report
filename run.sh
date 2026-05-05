#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

cd "$SCRIPT_DIR"

if [[ ! -d "$VENV" ]]; then
    echo "No virtual environment found. Creating one..."
    python3 -m venv "$VENV"
fi

if [[ ! -f "$VENV/bin/legacy-report" ]]; then
    echo "Installing dependencies..."
    "$VENV/bin/pip" install -e . --quiet
fi

exec "$VENV/bin/legacy-report"
