#!/usr/bin/env sh
# Stable OpenClaw entrypoint. Uses the repo-local virtualenv when present.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

exec "$PYTHON" "$REPO_ROOT/scripts/openclaw_analyze.py" "$@"
