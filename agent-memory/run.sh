#!/usr/bin/env bash
# One command: build + start the full stack (Docker), then run the demo simulation.
# Needs only Docker with Compose v2 — no Python or Node on the host.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose not found. Install Docker Desktop or the compose plugin:" >&2
  echo "  https://docs.docker.com/compose/install/" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but not running. Start Docker Desktop (or dockerd) and retry." >&2
  exit 1
fi

echo "Step 1/2: Building and starting containers (first run takes a few minutes)..."
if ! "${COMPOSE[@]}" up --build --detach --wait --wait-timeout 300; then
  echo "" >&2
  echo "Stack did not become healthy. Recent API logs:" >&2
  "${COMPOSE[@]}" logs --tail=40 api >&2 || true
  exit 1
fi

echo "Step 2/2: Running the demo simulation inside the api container..."
"${COMPOSE[@]}" exec -T api python backend/demo_simulation.py

host_port() { "${COMPOSE[@]}" port "$1" "$2" | sed 's/.*://'; }
API_PORT="$(host_port api 8000)"
FRONTEND_PORT="$(host_port frontend 80)"

echo ""
echo "All systems go."
echo "Dashboard: http://localhost:${FRONTEND_PORT}"
echo "API:       http://localhost:${API_PORT}"
echo "API Docs:  http://localhost:${API_PORT}/docs"
echo "Logs:      ${COMPOSE[*]} logs -f api"
echo "Stop:      ${COMPOSE[*]} down        (add -v to also wipe the database)"
