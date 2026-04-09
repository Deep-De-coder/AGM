#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting AgentMemory in dev mode (no Docker)..."
echo "Requires: PostgreSQL and Redis running locally"
echo ""
echo "Installing Python deps..."
pip install -r requirements.txt -q
echo "Running migrations..."
alembic upgrade head
echo "Starting API server in background..."
export PYTHONPATH="$SCRIPT_DIR"
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
API_PID=$!
echo "API running at http://localhost:8000 (PID: $API_PID)"
echo "Starting frontend in background..."
cd frontend && npm install -q && npm run dev &
FRONTEND_PID=$!
echo "Frontend running at http://localhost:5173 (PID: $FRONTEND_PID)"
echo ""
echo "Press Ctrl+C to stop everything"
trap "kill $API_PID $FRONTEND_PID 2>/dev/null || true" EXIT
wait
