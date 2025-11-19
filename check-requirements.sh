#!/usr/bin/env bash
# check-requirements.sh
# Simple script to confirm required CLI/tools are installed.

set -euo pipefail

missing=0

echo "Checking requirements for repository: $(basename "$(pwd)")"

# Check Python (prefer python3)
PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN=python
fi

if [ -n "$PYTHON_BIN" ]; then
  PYVER=$($PYTHON_BIN --version 2>&1)
  echo "Found Python: $PYVER (command: $PYTHON_BIN)"
else
  echo "ERROR: Python is not installed or not on PATH. Please install Python 3.x." >&2
  missing=1
fi

# Check kubeseal
if command -v kubeseal >/dev/null 2>&1; then
  KUBESEAL_VER=$(kubeseal --version 2>&1 || true)
  echo "Found kubeseal: $KUBESEAL_VER"
else
  echo "ERROR: kubeseal is not installed or not on PATH. Install from https://github.com/bitnami-labs/sealed-secrets" >&2
  missing=1
fi

if [ "$missing" -ne 0 ]; then
  echo "One or more requirements are missing." >&2
  exit 2
fi

echo "All requirements satisfied." 
exit 0
