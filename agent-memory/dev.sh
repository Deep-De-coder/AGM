#!/usr/bin/env bash
# Hot-reload dev mode: API (uvicorn --reload) and dashboard (Vite) run on your host.
# Postgres + Redis come from docker compose; set SKIP_INFRA=1 to use your own
# (then point DATABASE_URL / REDIS_URL in .env at them).
# Needs: Python 3.11+, Node 18+, and Docker unless SKIP_INFRA=1.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  echo "Python 3.11+ is required (tried '$PYTHON'). Set PYTHON=/path/to/python3.11 and retry." >&2
  exit 1
fi

# A project-local venv avoids "externally-managed-environment" errors (PEP 668).
if [ ! -d .venv ]; then
  echo "Creating virtualenv in .venv ..."
  "$PYTHON" -m venv .venv
fi
VENV_BIN=.venv/bin
[ -d .venv/Scripts ] && VENV_BIN=.venv/Scripts  # Git Bash on Windows
echo "Installing Python deps..."
"$VENV_BIN/python" -m pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if [ "${SKIP_INFRA:-0}" != "1" ]; then
  echo "Starting Postgres + Redis (docker compose)..."
  docker compose up --detach --wait postgres redis
fi

echo "Running migrations..."
export PYTHONPATH="$SCRIPT_DIR"
"$VENV_BIN/python" -m alembic upgrade head

# Stop both servers (and their children) on Ctrl+C or exit.
trap 'trap - EXIT INT TERM; kill 0 2>/dev/null' EXIT INT TERM

API_PORT="${API_PORT:-8000}"
export PROXY_API_TARGET="http://localhost:${API_PORT}"
"$VENV_BIN/python" -m uvicorn backend.main:app --host 0.0.0.0 --port "$API_PORT" --reload &
(cd frontend && npm install --no-audit --no-fund && npm run dev) &

echo ""
echo "API:       http://localhost:${API_PORT}  (docs: /docs)"
echo "Dashboard: http://localhost:5173"
echo "Press Ctrl+C to stop everything"
wait
