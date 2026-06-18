#!/bin/zsh
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install -r "${GATEWAY_REQUIREMENTS:-requirements-lock.txt}"
if [ ! -d "frontend/node_modules" ]; then
  (cd frontend && npm ci --no-audit)
fi
(cd frontend && npm run build)
exec .venv/bin/python gateway_api.py
