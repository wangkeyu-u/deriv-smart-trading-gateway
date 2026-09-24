from __future__ import annotations

import time
from typing import Any

import httpx
import streamlit as st

import jev_router
import web_app


def jev_response(choice: str, fast: float, confidence: float) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "jev-1.13.0",
            "answers": {
                "thinking_path": {
                    "type": "choice",
                    "choice": choice,
                    "probabilities": {"fast": fast, "deep": 1 - fast},
                    "confidence": confidence,
                }
            },
        },
        request=httpx.Request("POST", jev_router.JEV_ENDPOINT),
    )


def test_jev_fast_route_uses_documented_contract_and_short_timeout(monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        seen.update({"url": url, **kwargs})
        return jev_response("fast", 0.93, 0.85)

    monkeypatch.setattr(jev_router.httpx, "post", fake_post)
    route = jev_router.route_thinking({"task": "read_only_manager_routing"}, "test-key")
    assert route.mode == "fast"
    assert route.source == "jev"
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["json"]["questions"]["thinking_path"]["type"] == "choice"
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    assert seen["timeout"] <= 1.2


def test_uncertain_or_invalid_jev_answer_keeps_deeper_path(monkeypatch: Any) -> None:
    monkeypatch.setattr(jev_router.httpx, "post", lambda *args, **kwargs: jev_response("fast", 0.6, 0.4))
    assert jev_router.route_thinking({}, "test-key").mode == "deep"

    monkeypatch.setattr(jev_router.httpx, "post", lambda *args, **kwargs: jev_response("execute_trade", 1.0, 1.0))
    route = jev_router.route_thinking({}, "test-key")
    assert route.mode == "deep"
    assert route.source == "jev_error"


def test_jev_timeout_keeps_deeper_path_and_deadline_skips_network(monkeypatch: Any) -> None:
    def timeout(*args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(jev_router.httpx, "post", timeout)
    route = jev_router.route_thinking({}, "test-key")
    assert route.mode == "deep"
    assert route.source == "jev_error"

    route = jev_router.route_thinking({}, "test-key", deadline_at=time.perf_counter() + 1)
    assert route.mode == "fast"
    assert route.source == "deadline"


def test_only_explicit_read_only_requests_can_use_manager_fast_path() -> None:
    assert web_app.jev_read_only_candidate("查看 R_100 最新 Tick 行情")
    assert web_app.jev_read_only_candidate("画 R_75 K线图")
    assert not web_app.jev_read_only_candidate("R_100 下跌时买 10 USD CALL")
    assert not web_app.jev_read_only_candidate("平仓合同 123456")
    assert not web_app.jev_read_only_candidate("按当前价格卖出 R_100 合约")
    assert not web_app.jev_read_only_candidate("解释一下什么是复利")


def test_manager_uses_jev_only_for_read_only_request(monkeypatch: Any) -> None:
    st.session_state.clear()
    web_app.init_state()
    st.session_state.llm_provider = "OpenAI"
    st.session_state.llm_api_key = "model-key"
    st.session_state.jev_enabled = True
    st.session_state.jev_api_key = "jev-key"
    calls: list[str] = []

    def fake_route(*args: Any, **kwargs: Any) -> jev_router.ThinkingRoute:
        calls.append("jev")
        return jev_router.ThinkingRoute("fast", "jev", 10, 0.9, 0.95)

    def fake_local(*args: Any, **kwargs: Any) -> web_app.TeamRunResult:
        calls.append("local")
        return web_app.TeamRunResult("local answer", [])

    def fake_manager(*args: Any, **kwargs: Any) -> web_app.TeamRunResult:
        calls.append("manager")
        return web_app.TeamRunResult("manager answer", [])

    monkeypatch.setattr(web_app, "route_thinking", fake_route)
    monkeypatch.setattr(web_app, "deterministic_manager_state_machine", fake_local)
    monkeypatch.setattr(web_app, "manager_with_openai_tool_calling", fake_manager)

    result = web_app.run_hierarchical_trading_team("查看 R_100 行情")
    assert result.final_answer == "local answer"
    assert result.thinking_route and result.thinking_route["mode"] == "fast"
    assert calls == ["jev", "local"]

    calls.clear()
    result = web_app.run_hierarchical_trading_team("按当前价格卖出 R_100 合约")
    assert result.final_answer == "manager answer"
    assert calls == ["manager"]
