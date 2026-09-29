from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import pytest
import streamlit as st

import jev_router
import web_app
from evals.scenarios import choice, response, snapshot


def install_response(monkeypatch, body=None, status=200, delay=0):
    seen = []
    async def post(self, url, **kwargs):
        seen.append({"url": url, **kwargs})
        await asyncio.sleep(delay)
        return httpx.Response(status, json=body or response(), request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    return seen


def test_batch_contract_and_model_version(monkeypatch):
    seen = install_response(monkeypatch, response(thesis="supported"))
    result = jev_router.assess_market({"scene": "review", "evidence": {"trend": "up"}}, "test-key", deadline_at=time.perf_counter() + 5)
    assert result.source == "jev"
    assert result.reasoning_path == "finish"
    assert result.thesis_status == "supported"
    assert result.model == "jev-1.13.0"
    assert len(seen) == 1
    assert set(seen[0]["json"]["questions"]) == {"market_stance", "reasoning_path", "thesis_status"}
    assert seen[0]["headers"]["Authorization"] == "Bearer test-key"
    assert "test-key" not in str(result.as_dict())


@pytest.mark.parametrize("bad", [True, "0.94", float("nan"), float("inf"), -0.2, 1.1])
def test_non_numeric_or_out_of_range_probabilities_rejected(monkeypatch, bad):
    body = response()
    body["answers"]["market_stance"]["probabilities"]["CALL"] = bad
    monkeypatch.setattr(jev_router, "_request", lambda *args: body)
    result = jev_router.assess_market({}, "key", deadline_at=time.perf_counter() + 5)
    assert result.source == "jev_error"
    assert result.error_code == "invalid_response"
    assert result.stance is None


@pytest.mark.parametrize("mutation", ["missing_path", "wrong_choice", "probability_sum", "missing_model", "missing_thesis"])
def test_partial_and_inconsistent_batch_never_accepts_stance(monkeypatch, mutation):
    body = response(thesis="supported")
    if mutation == "missing_path":
        del body["answers"]["reasoning_path"]
    elif mutation == "wrong_choice":
        body["answers"]["market_stance"]["choice"] = "PUT"
    elif mutation == "probability_sum":
        body["answers"]["market_stance"]["probabilities"]["PUT"] = .4
    elif mutation == "missing_model":
        del body["model"]
    else:
        del body["answers"]["thesis_status"]
    monkeypatch.setattr(jev_router, "_request", lambda *args: body)
    result = jev_router.assess_market({"scene": "review"}, "key", deadline_at=time.perf_counter() + 5)
    assert result.error_code == "invalid_response"
    assert result.stance is None


@pytest.mark.parametrize("status,code", [(401, "authentication"), (422, "request_invalid"), (429, "rate_limited"), (529, "overloaded")])
def test_service_errors_are_distinct_and_not_retried(monkeypatch, status, code):
    seen = install_response(monkeypatch, status=status)
    result = jev_router.assess_market({}, "key", deadline_at=time.perf_counter() + 5)
    assert result.error_code == code
    assert len(seen) == 1


def test_total_deadline_cancels_slow_response(monkeypatch):
    seen = install_response(monkeypatch, delay=2)
    started = time.perf_counter()
    result = jev_router.assess_market({}, "key", deadline_at=started + .5)
    assert time.perf_counter() - started < .8
    assert result.error_code == "timeout"
    assert len(seen) == 1


def test_missing_key_and_deadline_do_not_call_network(monkeypatch):
    seen = install_response(monkeypatch)
    assert jev_router.assess_market({}, "", deadline_at=time.perf_counter() + 5).source == "disabled"
    assert jev_router.assess_market({}, "key", deadline_at=time.perf_counter()).source == "deadline"
    route = jev_router.route_thinking({}, "key", deadline_at=time.perf_counter() + 1)
    assert route.mode == "wait"
    assert seen == []


def test_manager_fast_path_requires_decisive_distribution(monkeypatch):
    install_response(monkeypatch, {"answers": {"thinking_path": choice("fast", ["fast", "deep"])}})
    assert jev_router.route_thinking({}, "key").mode == "fast"
    install_response(monkeypatch, {"answers": {"thinking_path": choice("fast", ["fast", "deep"], .6)}})
    assert jev_router.route_thinking({}, "key").mode == "deep"


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
