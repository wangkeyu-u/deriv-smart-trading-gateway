#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"

cd "${ROOT_DIR}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

"${PYTHON_BIN}" -m pip install --upgrade pip
"${PYTHON_BIN}" -m pip install -r requirements.txt
"${PYTHON_BIN}" -m pip install -r desktop_requirements.txt
"${PYTHON_BIN}" -m pip install -r desktop_packaging_requirements.txt
"${PYTHON_BIN}" -m PyInstaller --clean --noconfirm packaging/pyinstaller/deriv_gateway_desktop.spec

echo "Built desktop app:"
echo "  ${ROOT_DIR}/dist/Deriv Smart Trading Gateway.app"
