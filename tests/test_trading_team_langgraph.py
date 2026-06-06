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
