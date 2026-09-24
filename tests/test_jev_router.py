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


def test_market_assessment_sends_market_evidence_and_validates_choice(monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        seen.update({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "market_stance": {
                        "type": "choice",
                        "choice": "CALL",
                        "probabilities": {"CALL": 0.91, "PUT": 0.02, "WAIT": 0.07},
                        "confidence": 0.84,
                    }
                },
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(jev_router.httpx, "post", fake_post)
    assessment = jev_router.assess_market(
        {"symbol": "R_75", "market": {"trend": "up", "ma5": 101, "ma20": 99}},
        "test-key",
        deadline_at=time.perf_counter() + 5,
    )
    assert assessment.stance == "CALL"
    assert assessment.probabilities and assessment.probabilities["CALL"] == 0.91
    assert seen["json"]["state"]["market"]["ma5"] == 101
    assert seen["json"]["questions"]["market_stance"]["criteria"].keys() == {"CALL", "PUT", "WAIT"}
    assert seen["timeout"] <= 1.2


def test_jev_advice_changes_direction_only_with_market_support() -> None:
    local = {"stance": "WAIT", "confidence": 0.65, "summary": "local wait", "vote_counts": {"CALL": 2, "PUT": 0, "WAIT": 3}}
    call = jev_router.MarketAssessment("CALL", "jev", 80, 0.88, {"CALL": 0.92, "PUT": 0.02, "WAIT": 0.06})
    promoted = web_app.combine_jev_advice(local, {"tick": {"quote": 101}, "trend": "up"}, call)
    assert promoted["stance"] == "CALL"
    assert "Jev" in promoted["summary"]

    unsupported = web_app.combine_jev_advice(local, {"tick": {"quote": 101}, "trend": "down"}, call)
    assert unsupported["stance"] == "WAIT"

    opposing_local = {**local, "stance": "PUT"}
    conflict = web_app.combine_jev_advice(opposing_local, {"tick": {"quote": 101}, "trend": "up"}, call)
    assert conflict["stance"] == "WAIT"

    weak = jev_router.MarketAssessment("CALL", "jev", 80, 0.4, {"CALL": 0.6, "PUT": 0.1, "WAIT": 0.3})
    assert web_app.combine_jev_advice(local, {"tick": {"quote": 101}, "trend": "up"}, weak)["stance"] == "WAIT"


def test_advisor_jev_opinion_is_used_without_slow_synthesis(monkeypatch: Any) -> None:
    st.session_state.clear()
    web_app.init_state()
    st.session_state.jev_enabled = True
    st.session_state.jev_api_key = "jev-key"
    monkeypatch.setattr(web_app, "in_streamlit_runtime", lambda: True)
    monkeypatch.setattr(web_app, "push_runtime_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        web_app,
        "assess_market",
        lambda *args, **kwargs: jev_router.MarketAssessment(
            "CALL", "jev", 50, 0.9, {"CALL": 0.95, "PUT": 0.01, "WAIT": 0.04}
        ),
    )
    monkeypatch.setattr(
        web_app,
        "advisor_llm_synthesis",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("slow model should be skipped")),
    )
    local = {"stance": "WAIT", "confidence": 0.65, "summary": "local wait", "vote_counts": {"CALL": 2, "PUT": 0, "WAIT": 3}}
    summary, route, assessment, consensus, opinions = web_app.advisor_synthesis_with_jev(
        "R_75?", "R_75", {"tick": {"quote": 101}, "trend": "up", "ma5": 101, "ma20": 99}, [], [], local, time.perf_counter(), 10
    )
    assert summary is None
    assert route["source"] == "jev_decision"
    assert assessment["stance"] == "CALL"
    assert consensus["stance"] == "CALL"
    assert opinions[0]["advisor_id"] == "jev"


def test_advisor_skips_jev_when_market_data_missing(monkeypatch: Any) -> None:
    st.session_state.clear()
    web_app.init_state()
    st.session_state.jev_enabled = True
    st.session_state.jev_api_key = "jev-key"
    monkeypatch.setattr(web_app, "in_streamlit_runtime", lambda: True)
    monkeypatch.setattr(web_app, "push_runtime_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(web_app, "assess_market", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no market call")))
    monkeypatch.setattr(web_app, "advisor_llm_synthesis", lambda *args, **kwargs: None)
    local = {"stance": "WAIT", "confidence": 0.4, "summary": "wait", "vote_counts": {"CALL": 0, "PUT": 0, "WAIT": 5}}
    _, route, assessment, consensus, opinions = web_app.advisor_synthesis_with_jev(
        "R_75?", "R_75", {}, [], [], local, time.perf_counter(), 10
    )
    assert assessment["source"] == "no_current_tick"
    assert route["mode"] == "fast"
    assert consensus["stance"] == "WAIT"
    assert opinions == []


def test_stale_tick_does_not_reach_jev(monkeypatch: Any) -> None:
    st.session_state.clear()
    web_app.init_state()
    st.session_state.jev_enabled = True
    st.session_state.jev_api_key = "jev-key"
    monkeypatch.setattr(web_app, "in_streamlit_runtime", lambda: True)
    monkeypatch.setattr(web_app, "push_runtime_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(web_app, "assess_market", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("stale tick")))
    monkeypatch.setattr(web_app, "advisor_llm_synthesis", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("stale tick")))
    local = {"stance": "CALL", "confidence": 0.8, "summary": "local call", "vote_counts": {"CALL": 4, "PUT": 0, "WAIT": 1}}
    _, _, assessment, consensus, _ = web_app.advisor_synthesis_with_jev(
        "R_75?", "R_75", {"tick": {"quote": 100, "epoch": time.time() - 120}, "trend": "up"},
        [], [], local, time.perf_counter(), 10
    )
    assert assessment["source"] == "no_current_tick"
    assert consensus["stance"] == "WAIT"


def test_langgraph_result_includes_jev_opinion_and_final_stance(monkeypatch: Any) -> None:
    st.session_state.clear()
    web_app.init_state()
    st.session_state.jev_enabled = True
    st.session_state.jev_api_key = "jev-key"
    monkeypatch.setattr(web_app, "in_streamlit_runtime", lambda: True)
    monkeypatch.setattr(web_app, "push_runtime_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(web_app, "collect_advisor_web_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        web_app,
        "advisor_market_snapshot",
        lambda *args, **kwargs: {
            "symbol": "R_75",
            "tick": {"quote": 101.0},
            "trend": "up",
            "ma5": 101.0,
            "ma20": 99.0,
            "summary": "R_75 trend up",
        },
    )
    monkeypatch.setattr(
        web_app,
        "assess_market",
        lambda *args, **kwargs: jev_router.MarketAssessment(
            "WAIT", "jev", 45, 0.92, {"CALL": 0.02, "PUT": 0.01, "WAIT": 0.97}
        ),
    )
    result = web_app.build_advisor_langgraph().invoke(
        {
            "question": "Should I wait?",
            "symbol": "R_75",
            "budget": 10,
            "use_web": False,
            "language": "zh",
            "jev_enabled": True,
            "jev_api_key": "jev-key",
            "started_at": time.perf_counter(),
            "opinions": [],
            "logs": [],
        }
    )
    assert result["jev_assessment"]["stance"] == "WAIT"
    assert any(opinion["advisor_id"] == "jev" for opinion in result["opinions"])
    assert result["stance"] == "WAIT"
    assert "Jev" in result["consensus"]
