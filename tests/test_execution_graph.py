from __future__ import annotations

from typing import Any

import streamlit as st

import web_app


EXECUTION_ROLES = {
    "manager",
    "strategy",
    "market",
    "risk",
    "compliance",
    "chart",
    "execution",
    "report",
}


def graph_nodes(graph: Any) -> set[str]:
    return set(graph.get_graph().nodes)


def graph_edges(graph: Any) -> set[tuple[str, str]]:
    return {(edge.source, edge.target) for edge in graph.get_graph().edges}


def test_execution_graph_contains_exactly_eight_role_nodes_plus_safety_gate() -> None:
    graph = web_app.build_execution_langgraph()
    nodes = graph_nodes(graph)
    assert EXECUTION_ROLES <= nodes
    assert "safety_gate" in nodes
    assert EXECUTION_ROLES.isdisjoint({"safety_gate", "__start__", "__end__"})
    assert ("chart", "safety_gate") in graph_edges(graph)
    assert ("safety_gate", "execution") in graph_edges(graph)
    assert ("safety_gate", "report") in graph_edges(graph)


def test_parent_graph_exposes_mutually_exclusive_subgraph_boundaries() -> None:
    graph = web_app.build_gateway_parent_graph()
    nodes = graph_nodes(graph)
    edges = graph_edges(graph)
    assert nodes == {"__start__", "__end__", "execution_subgraph", "advisor_subgraph"}
    assert ("__start__", "execution_subgraph") in edges
    assert ("__start__", "advisor_subgraph") in edges
    assert ("advisor_subgraph", "execution_subgraph") not in edges
    assert ("execution_subgraph", "advisor_subgraph") not in edges


def test_parallel_advisor_reducer_preserves_every_opinion(monkeypatch: Any) -> None:
    monkeypatch.setattr(web_app, "collect_advisor_web_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        web_app,
        "advisor_market_snapshot",
        lambda *args, **kwargs: {"symbol": "R_75", "trend": "flat", "summary": "fixture"},
    )
    state = web_app.build_advisor_langgraph().invoke(
        {
            "question": "wait?",
            "symbol": "R_75",
            "budget": 4,
            "use_web": False,
            "language": "en",
            "started_at": 0.0,
            "opinions": [],
            "logs": [],
        }
    )
    expected = {item["id"] for item in web_app.advisor_specs()}
    actual = {item["advisor_id"] for item in state["opinions"]}
    assert actual == expected
    assert len(state["opinions"]) == len(expected)


def test_safety_gate_rejects_missing_parameters_before_execution() -> None:
    decision = web_app.execution_safety_decision(
        {
            "plan": {
                "trade_intent": True,
                "amount": 0,
                "contract_type": "",
            },
            "agent_reports": {"compliance": {"ok": False, "blockers": ["missing_amount"]}},
        }
    )
    assert decision["allow_execution"] is False
    assert decision["reason"] == "missing_trade_parameters"


def test_execution_graph_routes_only_cleared_trade_to_execution(monkeypatch: Any) -> None:
    called: list[str] = []

    def fake_role(name: str, report: dict[str, Any]):
        def call(arguments: dict[str, Any], events: list[Any], writer: Any = None) -> dict[str, Any]:
            called.append(name)
            return report

        return call

    monkeypatch.setattr(
        web_app,
        "assign_task_to_strategy_agent",
        fake_role("strategy", {"role": "Strategy Researcher", "ok": True}),
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_market_agent",
        fake_role(
            "market",
            {"role": "Market Analyst Agent", "ok": True, "tick_analysis": {"latest_quote": 100.0}},
        ),
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_risk_agent",
        fake_role("risk", {"role": "Risk Sentinel", "ok": True}),
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_compliance_agent",
        fake_role("compliance", {"role": "Compliance Reviewer", "ok": True}),
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_execution_agent",
        fake_role("execution", {"role": "Execution Trader", "ok": False, "reason": "pending_human_confirmation"}),
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_report_agent",
        fake_role("report", {"role": "Report Agent", "ok": True}),
    )

    result = web_app.run_execution_langgraph("用 10 美金买 R_75 看涨，持续 5 ticks")
    assert called == ["strategy", "market", "risk", "compliance", "execution", "report"]
    assert result.execution_report is not None
    assert result.execution_report["reason"] == "pending_human_confirmation"


def test_execution_graph_skips_write_role_when_condition_fails(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        web_app,
        "assign_task_to_strategy_agent",
        lambda *args, **kwargs: {"role": "Strategy Researcher", "ok": True},
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_market_agent",
        lambda *args, **kwargs: {
            "role": "Market Analyst Agent",
            "ok": True,
            "tick_analysis": {"latest_quote": 100.0, "consecutive_three_down": False},
        },
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_risk_agent",
        lambda *args, **kwargs: {"role": "Risk Sentinel", "ok": True},
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_compliance_agent",
        lambda *args, **kwargs: {"role": "Compliance Reviewer", "ok": True},
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_execution_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("write role must be skipped")),
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_report_agent",
        lambda *args, **kwargs: {"role": "Report Agent", "ok": True},
    )

    result = web_app.run_execution_langgraph(
        "如果连续三个 Tick 都在跌，用 10 美金买 R_75 看涨，持续 5 ticks"
    )
    assert result.execution_report is not None
    assert result.execution_report["reason"] == "condition_not_met"
    assert result.execution_report["status"] == "not_invoked"


def test_runtime_falls_back_deterministically_when_graph_fails(monkeypatch: Any) -> None:
    sentinel = web_app.TeamRunResult("fallback", [], ok=True)
    monkeypatch.setattr(
        web_app, "run_execution_langgraph", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr(web_app, "deterministic_manager_state_machine", lambda *args, **kwargs: sentinel)
    result = web_app.run_hierarchical_trading_team("check R_75")
    assert result is sentinel


def test_advisor_parent_route_never_calls_execution_role(monkeypatch: Any) -> None:
    st.session_state.llm_provider = "本地规则"
    monkeypatch.setattr(web_app, "collect_advisor_web_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        web_app,
        "advisor_market_snapshot",
        lambda *args, **kwargs: {"symbol": "R_75", "trend": "flat", "summary": "fixture"},
    )
    monkeypatch.setattr(
        web_app,
        "assign_task_to_execution_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("advisor crossed safety boundary")),
    )
    result = web_app.run_advisor_langgraph("what now?", "R_75", 4, False)
    assert result is not None
    assert result["graph_runtime"] == "langgraph"
