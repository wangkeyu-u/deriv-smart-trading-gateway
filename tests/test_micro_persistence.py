from __future__ import annotations

import web_app
from micro_trading import MicroTradeConfig


def test_micro_strategy_run_persistence(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_app, "DB_PATH", tmp_path / "gateway.sqlite3")

    config = MicroTradeConfig(symbol="R_75", max_trade_amount=1.0)
    web_app.save_micro_strategy_run(
        goal="small fast paper strategy",
        config=config,
        decision={"action": "CALL", "confidence": 0.72},
        budget_check={"ok": True, "reason": "within_budget"},
        backtest={"summary": {"trade_count": 3, "total_pnl": 0.012, "halted": False}, "trades": []},
    )

    rows = web_app.load_recent_micro_strategy_runs(limit=3)

    assert len(rows) == 1
    assert rows[0]["symbol"] == "R_75"
    assert rows[0]["action"] == "CALL"
    assert rows[0]["budget_ok"] == 1
    assert rows[0]["trade_count"] == 3
    assert rows[0]["total_pnl"] == 0.012


def test_session_hydrates_latest_local_workspace(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_app, "DB_PATH", tmp_path / "gateway.sqlite3")

    web_app.st.session_state.clear()
    web_app.init_state()
    web_app.st.session_state.agent_execution_log = "persisted execution log"
    team_result = web_app.TeamRunResult(
        final_answer="manager restored answer",
        events=[web_app.AgentEvent("经理", "用户", "manager restored answer")],
        market_report={"summary": "market restored"},
        execution_report={"ok": False, "reason": "missing_deriv_api_token"},
        ok=False,
    )
    web_app.save_team_run("restore this prompt", team_result)
    web_app.save_advisor_run(
        {
            "question": "restore advisor",
            "symbol": "R_75",
            "consensus": "WAIT",
            "confidence": 0.61,
            "elapsed_ms": 12.0,
            "stance": "WAIT",
        }
    )
    web_app.append_agent_memory_to_state(
        web_app.st.session_state,
        "market",
        {"time": "10:00:00", "task": "R_75", "summary": "market memory", "ok": True},
        persist=True,
    )

    web_app.st.session_state.clear()
    web_app.init_state()
    web_app.hydrate_persisted_session_state()

    assert web_app.st.session_state.messages == [
        {"role": "user", "content": "restore this prompt"},
        {"role": "assistant", "content": "manager restored answer"},
    ]
    assert web_app.st.session_state.agent_execution_log == "persisted execution log"
    assert web_app.st.session_state.team_events == ["[经理 ➔ 用户]：manager restored answer"]
    assert web_app.st.session_state.agent_reports["market"]["report"]["summary"] == "market restored"
    assert web_app.st.session_state.last_advisor_result["symbol"] == "R_75"
    assert web_app.st.session_state.agent_memory["market"][-1]["summary"] == "market memory"
