#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
PORT="${QUALITY_GATE_PORT:-8876}"
LOG_FILE="${TMPDIR:-/tmp}/deriv-gateway-quality-${PORT}.log"

if [ ! -x "$PYTHON" ]; then
  echo "Python runtime not found: $PYTHON" >&2
  exit 1
fi

echo "[1/5] Checking installed Python dependencies"
"$PYTHON" -m pip check

echo "[2/5] Compiling Python modules"
PYTHON_FILES=()
while IFS= read -r file; do
  PYTHON_FILES+=("$file")
done < <(rg --files -g '*.py' -g '!.venv/**')
if [ "${#PYTHON_FILES[@]}" -eq 0 ]; then
  echo "No Python modules found." >&2
  exit 1
fi
"$PYTHON" -m py_compile "${PYTHON_FILES[@]}"

echo "[3/5] Running Python test suite"
"$PYTHON" -m pytest -q

echo "[4/5] Installing and building the locked frontend"
(cd frontend && npm ci --no-audit --prefer-offline && npm run build)

echo "[5/5] Running API and SSE smoke checks"
"$PYTHON" -m uvicorn gateway_api:app --host 127.0.0.1 --port "$PORT" >"$LOG_FILE" 2>&1 &
SERVER_PID=$!
cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for attempt in $(seq 1 40); do
  if curl --fail --silent "http://127.0.0.1:${PORT}/api/health" >/dev/null; then
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    cat "$LOG_FILE" >&2
    exit 1
  fi
  sleep 0.25
done

curl --fail --silent "http://127.0.0.1:${PORT}/api/health" | grep -q '"ok":true'
curl --fail --silent \
  -H 'Content-Type: application/json' \
  -d '{"message":"介绍一下你的能力","provider":"local","language":"zh"}' \
  "http://127.0.0.1:${PORT}/api/chat/stream" | grep -q '"type": "done"'

echo "Quality gate passed."
