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
    result = web_app.run_advisor_council("EURUSD?", "frxEURUSD", 6, True)
    assert result["runtime"] == "langgraph"
    assert result["market"]["tick"]["quote"] == 100.0


def test_configured_key_reaches_adapter_but_not_graph_state(monkeypatch: Any) -> None:
    from evals.scenarios import snapshot, response
    import jev_router
    st.session_state.clear()
    web_app.init_state()
    st.session_state.jev_enabled = True
    st.session_state.jev_api_key = "configured-key"
    seen = []
    monkeypatch.setattr(web_app, "in_streamlit_runtime", lambda: True)
    monkeypatch.setattr(web_app, "advisor_market_snapshot", lambda *a, **k: snapshot())
    def request(state, questions, key, model, seconds):
        seen.append(key)
        return response()
    monkeypatch.setattr(jev_router, "_request", request)
    result = web_app.run_advisor_langgraph("trend?", "frxEURUSD", 6, False)
    assert result is not None and result["jev_assessment"]["source"] == "jev"
    assert seen == ["configured-key"]
    assert "configured-key" not in str(result)
    assert "jev_api_key" not in web_app.AdvisorGraphState.__annotations__
    assert "llm_config" not in web_app.AdvisorGraphState.__annotations__


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
    assert web_app.collect_advisor_web_context("EURUSD?", "frxEURUSD", 4, True) == []
    assert time.perf_counter() - started < 1.85


def test_synthetic_does_not_start_web_request(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("synthetic news must be skipped")
    monkeypatch.setattr(web_app, "fetch_news_rss", forbidden)
    assert web_app.collect_advisor_web_context("news?", "R_100", 10, True) == []


def test_fallback_uses_original_deadline(monkeypatch):
    from evals.scenarios import snapshot
    seen = []
    monkeypatch.setattr(web_app, "build_advisor_langgraph", lambda *a: (_ for _ in ()).throw(ImportError("absent")))
    def market(symbol, started, budget, *a, **k):
        seen.append(started)
        return snapshot(symbol)
    monkeypatch.setattr(web_app, "advisor_market_snapshot", market)
    result = web_app.run_advisor_council("observe", "R_100", 4, False)
    assert result["runtime"] == "local_fallback"
    assert len(seen) == 1
    assert result["stance"] == "WAIT"


def test_jev_path_reaches_ui_thread_before_explanation_finishes(monkeypatch):
    from evals.scenarios import snapshot, response
    import jev_router
    progress_received = threading.Event()
    ui_thread = threading.get_ident()
    messages = []
    callback_threads = []
    monkeypatch.setattr(web_app, "advisor_runtime_config", lambda: {
        "jev_enabled": True, "jev_api_key": "fixture-key", "jev_model": "jev-1.13.0",
        "llm_config": {"provider": "OpenAI", "api_key": "fixture-explanation-key", "model": "fixture"},
    })
    monkeypatch.setattr(web_app, "advisor_market_snapshot", lambda *a, **k: snapshot())
    monkeypatch.setattr(jev_router, "_request", lambda *a, **k: response(path="deep"))
    def explain(*a, **k):
        assert progress_received.wait(2), "UI did not receive progress while explanation was still running"
        return "Fixture explanation"
    def writer(message):
        messages.append(message)
        callback_threads.append(threading.get_ident())
        if message == "Progress -> explanation_start":
            progress_received.set()
    monkeypatch.setattr(web_app, "advisor_llm_synthesis", explain)
    result = web_app.run_advisor_langgraph("explain the window", "frxEURUSD", 6, False, writer)
    assert result is not None and not result.get("graph_error")
    assert result["model_summary"] == "Fixture explanation"
    assert messages.index("Progress -> jev_deep") < messages.index("Progress -> explanation_start") < messages.index("Progress -> explanation_done")
    assert set(callback_threads) == {ui_thread}
    assert "fixture-key" not in str(result) + str(messages)
    assert "fixture-explanation-key" not in str(result) + str(messages)
