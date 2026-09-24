from __future__ import annotations

from typing import Any
import threading
import time

import streamlit as st

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


def test_market_and_web_start_together(monkeypatch: Any) -> None:
    web_started = threading.Event()
    market_started = threading.Event()

    def fake_web(*args: Any, **kwargs: Any) -> list[dict[str, str]]:
        web_started.set()
        assert market_started.wait(1), "market snapshot did not start alongside web research"
        return []

    def fake_market(*args: Any, **kwargs: Any) -> dict[str, Any]:
        market_started.set()
        assert web_started.wait(1), "web research did not start alongside market snapshot"
        return {"symbol": "R_75", "tick": {"quote": 100.0}, "trend": "up", "summary": "test"}

    monkeypatch.setattr(web_app, "collect_advisor_web_context", fake_web)
    monkeypatch.setattr(web_app, "advisor_market_snapshot", fake_market)
    result = web_app.run_advisor_council("R_75?", "R_75", 6, True)
    assert result["runtime"] == "langgraph"
    assert result["market"]["tick"]["quote"] == 100.0


def test_graph_receives_configured_jev_key_from_ui(monkeypatch: Any) -> None:
    st.session_state.clear()
    web_app.init_state()
    st.session_state.jev_enabled = True
    st.session_state.jev_api_key = "configured-key"
    seen: dict[str, Any] = {}

    class RecordingGraph:
        def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
            seen.update(state)
            return state

    monkeypatch.setattr(web_app, "in_streamlit_runtime", lambda: True)
    monkeypatch.setattr(web_app, "build_advisor_langgraph", lambda: RecordingGraph())
    result = web_app.run_advisor_langgraph("R_75?", "R_75", 6, False)
    assert result is not None
    assert seen["jev_enabled"] is True
    assert seen["jev_api_key"] == "configured-key"


def test_failed_tick_uses_short_deadline_and_skips_candles(monkeypatch: Any) -> None:
    calls: list[tuple[str, float]] = []

    def fake_call(tool: str, factory: Any, params: dict[str, Any], deadline: float, *args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((tool, deadline - time.perf_counter()))
        return {"ok": False, "error": {"message": "offline"}}

    monkeypatch.setattr(web_app, "call_deriv_tool_before_deadline", fake_call)
    market = web_app.advisor_market_snapshot("R_75", time.perf_counter(), 10)
    assert market["tick"] is None
    assert len(calls) == 1
    assert calls[0][0] == "get_market_ticks"
    assert 0 < calls[0][1] <= 2.5


def test_web_research_returns_when_deadline_expires(monkeypatch: Any) -> None:
    monkeypatch.setattr(web_app, "build_advisor_queries", lambda *args: ["one"])

    def slow_fetch(*args: Any) -> list[dict[str, str]]:
        time.sleep(2)
        return []

    monkeypatch.setattr(web_app, "fetch_news_rss", slow_fetch)
    started = time.perf_counter()
    assert web_app.collect_advisor_web_context("R_75?", "R_75", 4, True) == []
    assert time.perf_counter() - started < 1.85
