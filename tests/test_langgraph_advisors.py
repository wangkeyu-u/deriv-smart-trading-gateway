from __future__ import annotations

from typing import Any

import web_app


def test_advisor_graph_compiles() -> None:
    graph = web_app.build_advisor_langgraph()
    assert type(graph).__name__ == "CompiledStateGraph"


def test_advisor_runtime_uses_langgraph(monkeypatch: Any) -> None:
    def fake_market_snapshot(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "symbol": "R_75",
            "tick": {"symbol": "R_75", "quote": 100.0},
            "trend": "up",
            "latest_close": 100.0,
            "summary": "R_75 fake trend=up",
        }

    monkeypatch.setattr(web_app, "collect_advisor_web_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app, "advisor_market_snapshot", fake_market_snapshot)

    result = web_app.run_advisor_council(
        "R_75 should we call?",
        "R_75",
        6,
        False,
        None,
    )
    assert result["runtime"] == "langgraph"
    assert result["ok"] is True
    assert result["symbol"] == "R_75"
    assert len(result["opinions"]) >= 5
    assert all("prompt" in item for item in result["opinions"])
    assert result["stance"] in {"CALL", "PUT", "WAIT"}


def test_advisor_runtime_degrades_when_market_and_web_fail(monkeypatch: Any) -> None:
    def fake_market_snapshot(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"symbol": "BAD", "summary": "no market data"}

    monkeypatch.setattr(web_app, "collect_advisor_web_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app, "advisor_market_snapshot", fake_market_snapshot)

    result = web_app.run_advisor_council(
        "BAD symbol should not crash",
        "BAD",
        4,
        True,
        None,
    )
    assert result["ok"] is True
    assert result["runtime"] == "langgraph"
    assert result["stance"] in {"CALL", "PUT", "WAIT"}
    assert len(result["opinions"]) >= 5
