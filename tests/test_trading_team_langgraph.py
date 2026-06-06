from __future__ import annotations

import web_app


def test_trading_team_graph_compiles() -> None:
    graph = web_app.build_trading_team_langgraph()

    assert type(graph).__name__ == "CompiledStateGraph"


def test_route_blocks_incomplete_plain_buy_before_execution() -> None:
    route = web_app.determine_agent_route("帮我买r100")

    assert route["symbol"] == "R_100"
    assert route["missing_fields"] == ["金额 amount", "方向 CALL/PUT"]
    assert route["route"] == ["strategy", "risk", "compliance", "report"]
    assert "execution" not in route["route"]
    assert "market" not in route["route"]


def test_route_complete_trade_enters_guarded_execution_chain() -> None:
    route = web_app.determine_agent_route("帮我用 1 美金买 R_100 看涨 5 ticks")

    assert route["missing_fields"] == []
    assert route["route"] == ["strategy", "market", "risk", "compliance", "execution", "report"]
    assert route["amount"] == 1
    assert route["contract_type"] == "CALL"
    assert route["duration"] == 5
    assert route["duration_unit"] == "t"


def test_incomplete_trade_graph_returns_clarification_without_execution() -> None:
    web_app.init_state()

    result = web_app.run_trading_team_langgraph("帮我买r100")

    assert "缺少交易参数" in result.final_answer
    assert "金额 amount" in result.final_answer
    assert "方向 CALL/PUT" in result.final_answer
    assert "execution" not in (result.agent_reports or {})
    assert "market" not in (result.agent_reports or {})


def test_team_graph_execution_blockers_include_risk_and_compliance() -> None:
    blockers = web_app.team_graph_execution_blockers(
        {
            "missing_fields": [],
            "guardrails": [],
            "agent_reports": {
                "risk": {"ok": False, "reason": "missing_deriv_api_token"},
                "compliance": {"ok": False, "blockers": ["missing_direction"]},
            },
        }
    )

    assert blockers == ["missing_deriv_api_token", "missing_direction"]


def test_complete_trade_without_token_is_graph_blocked_before_execution(monkeypatch) -> None:
    def fake_market_agent(args, events, writer=None):
        return {"role": "Market Analyst Agent", "ok": True, "summary": "fake market ok"}

    def fake_risk_agent(args, events, writer=None):
        return {"role": "Risk Sentinel", "ok": False, "status": "blocked", "reason": "missing_deriv_api_token"}

    def fail_execution(*args, **kwargs):
        raise AssertionError("execution_agent should be blocked by LangGraph guardrail")

    web_app.init_state()
    monkeypatch.setattr(web_app, "assign_task_to_market_agent", fake_market_agent)
    monkeypatch.setattr(web_app, "assign_task_to_risk_agent", fake_risk_agent)
    monkeypatch.setattr(web_app, "execution_agent", fail_execution)

    result = web_app.run_trading_team_langgraph("帮我用 1 美金买 R_100 看涨 5 ticks")

    assert result.execution_report is not None
    assert result.execution_report["reason"] == "graph_guardrail_blocked"
    assert "missing_deriv_api_token" in result.execution_report["blockers"]
    assert "没有提交订单" in result.final_answer
