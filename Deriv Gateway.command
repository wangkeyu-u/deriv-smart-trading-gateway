#!/bin/zsh
set -e

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi

requirements_hash="$(shasum -a 256 requirements.txt | awk '{print $1}')"
installed_hash="$(cat .venv/.requirements.sha256 2>/dev/null || true)"
if [ ! -x ".venv/bin/streamlit" ] || [ "$requirements_hash" != "$installed_hash" ]; then
  .venv/bin/python -m pip install -r requirements.txt
  print -r -- "$requirements_hash" > .venv/.requirements.sha256
fi

exec .venv/bin/streamlit run web_app.py --server.port 8501
