#!/bin/zsh
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r desktop_requirements.txt
.venv/bin/python desktop_app.py
