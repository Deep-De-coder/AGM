#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting AgentMemory full stack..."
echo "Step 1: Building containers..."
docker-compose build
echo "Step 2: Starting services..."
docker-compose up -d
echo "Step 3: Waiting for API to be healthy..."
until curl -sf http://localhost:8000/health > /dev/null; do
  echo "Waiting for API..."
  sleep 2
done
echo "Step 4: Running demo simulation..."
pip install httpx -q
export PYTHONPATH="$SCRIPT_DIR"
python backend/demo_simulation.py
echo ""
echo "All systems go."
echo "API:       http://localhost:8000"
echo "API Docs:  http://localhost:8000/docs"
echo "Dashboard: http://localhost:3000"
echo "Run 'docker-compose logs -f api' to watch logs"
