#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="docker compose -f ${ROOT}/docker-compose.dev.yml"

echo "[CI] Starting docker compose..."
$COMPOSE up -d

echo "[CI] Waiting for backend health..."
for i in {1..60}; do
  if curl -sf http://localhost:8000/health >/dev/null; then
    echo "[CI] Backend healthy"
    break
  fi
  sleep 2
done

cd "${ROOT}/frontend"
echo "[CI] Installing frontend deps..."
npm install
npx playwright install --with-deps

echo "[CI] Running Playwright E2E..."
E2E_BASE_URL=http://localhost:3000 NEXT_PUBLIC_API_URL=http://localhost:8000 npx playwright test

echo "[CI] Running backend pytest..."
cd "${ROOT}"
pytest backend/tests

echo "[CI] Shutting down compose..."
$COMPOSE down
