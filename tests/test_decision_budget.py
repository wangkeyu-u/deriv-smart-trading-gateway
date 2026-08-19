from __future__ import annotations

import time
from typing import Any

import streamlit as st

import web_app


def test_budget_is_clamped_to_implemented_range() -> None:
    assert web_app.normalize_decision_budget(-1) == 4
    assert web_app.normalize_decision_budget(4) == 4
    assert web_app.normalize_decision_budget(17) == 17
    assert web_app.normalize_decision_budget(25) == 25
    assert web_app.normalize_decision_budget(999) == 25


def test_execution_records_per_node_elapsed_and_remaining_budget(monkeypatch: Any) -> None:
    st.session_state.clear()
    web_app.init_state()
    monkeypatch.setattr(
        web_app,
        "assign_task_to_strategy_agent",
        lambda *args, **kwargs: {"role": "Strategy Researcher", "ok": True},
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_report_agent",
        lambda *args, **kwargs: {"role": "Report Agent", "ok": True},
    )
    result = web_app.run_execution_langgraph("解释系统架构", budget_seconds=4)
    evidence = result.runtime_evidence or {}
    assert evidence["budget_seconds"] == 4
    assert evidence["deadline_enforced"] is True
    assert evidence["observed_elapsed_ms"] < 4000
    timings = evidence["node_timings"]
    assert set(timings) == {
        "manager",
        "strategy",
        "market",
        "compliance",
        "risk",
        "chart",
        "safety_gate",
        "report",
    }
    assert all(item["elapsed_ms"] >= 0 for item in timings.values())
    assert all(item["remaining_after_ms"] <= 4000 for item in timings.values())


def test_deadline_exhaustion_fails_closed_before_execution(monkeypatch: Any) -> None:
    calls: list[str] = []

    def fast_role(name: str, report: dict[str, Any]):
        def call(*args: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append(name)
            return report

        return call

    monkeypatch.setattr(
        web_app,
        "assign_task_to_strategy_agent",
        fast_role("strategy", {"role": "Strategy Researcher", "ok": True}),
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_market_agent",
        fast_role("market", {"role": "Market Analyst Agent", "ok": True, "tick_analysis": {}}),
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_compliance_agent",
        fast_role("compliance", {"role": "Compliance Reviewer", "ok": True}),
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_risk_agent",
        fast_role("risk", {"role": "Risk Sentinel", "ok": True}),
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_execution_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("write role ran after timeout")),
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_report_agent",
        fast_role("report", {"role": "Report Agent", "ok": True}),
    )

    graph = web_app.build_execution_langgraph()
    state = graph.invoke(
        {
            "user_text": "用 10 美金买 R_100 看涨，持续 5 ticks",
            "budget_seconds": 4,
            "started_at": time.perf_counter() - 5,
            "deadline_at": time.perf_counter() - 1,
            "events": [],
            "graph_trace": [],
            "agent_reports": {},
            "node_timings": {},
        }
    )
    assert state["timed_out"] is True
    assert state["safety_decision"]["reason"] == "decision_deadline_exceeded"
    assert state["execution_report"]["status"] == "not_invoked"
    assert "execution" not in calls


def test_advisor_budget_telemetry_is_fixture_not_network_claim(monkeypatch: Any) -> None:
    monkeypatch.setattr(web_app, "collect_advisor_web_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        web_app,
        "advisor_market_snapshot",
        lambda *args, **kwargs: {"symbol": "R_100", "summary": "fixture market"},
    )
    result = web_app.run_advisor_council("fixture question", "R_100", 2, False)
    assert result["time_budget_seconds"] == 4
    assert result["deadline_enforced"] is True
    assert result["elapsed_ms"] < 4000
    # 3 input nodes + 5 parallel advisors + 1 Chief.
    assert len(result["node_timings"]) == 9
