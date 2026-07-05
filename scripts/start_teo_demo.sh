#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f ".env" ]]; then
  echo "Missing .env. Copy .env.example to .env and add keys."
  exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing .venv. Run: python3 -m venv .venv && source .venv/bin/activate && make install-dev"
  exit 1
fi

if [[ ! -d "apps/web/node_modules" ]]; then
  echo "Missing web dependencies. Run: cd apps/web && npm install"
  exit 1
fi

cleanup() {
  trap - INT TERM EXIT
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "Starting TEO API on http://127.0.0.1:8000"
.venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!

echo "Starting TEO Web on http://127.0.0.1:5173"
(cd apps/web && npm run dev -- --host 127.0.0.1) &
WEB_PID=$!

echo ""
echo "TEO demo is running."
echo "Open http://127.0.0.1:5173"
echo "Press Ctrl+C to stop."
wait
