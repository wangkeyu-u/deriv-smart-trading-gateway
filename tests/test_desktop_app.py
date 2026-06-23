from __future__ import annotations

from pathlib import Path

import desktop_app
import pytest


def test_configure_qt_plugin_path_sets_existing_directories(monkeypatch) -> None:
    pytest.importorskip("PySide6", reason="desktop dependency is optional in the core test job")
    monkeypatch.delenv("QT_PLUGIN_PATH", raising=False)
    monkeypatch.delenv("QT_QPA_PLATFORM_PLUGIN_PATH", raising=False)

    desktop_app._configure_qt_plugin_path()

    plugin_path = Path(__import__("os").environ["QT_PLUGIN_PATH"])
    platform_path = Path(__import__("os").environ["QT_QPA_PLATFORM_PLUGIN_PATH"])
    assert plugin_path.exists()
    assert platform_path.exists()
    assert platform_path.name == "platforms"
