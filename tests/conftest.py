from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    import web_app
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_app, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
