from __future__ import annotations

from typing import Any

import inspect
import pytest
import streamlit as st

import web_app


@pytest.fixture(autouse=True)
def reset_state() -> None:
    st.session_state.clear()
    web_app.init_state()


def test_compliance_blocks_missing_amount_and_direction() -> None:
    events: list[web_app.AgentEvent] = []
    report = web_app.compliance_agent(
        task="帮我下单 R_75",
        amount=0,
        contract_type="",
        events=events,
    )
    assert report["ok"] is False
    assert "missing_amount" in report["blockers"]
    assert "missing_direction" in report["blockers"]


def test_execution_blocks_when_token_missing() -> None:
    events: list[web_app.AgentEvent] = []
    report = web_app.execution_agent(
        task="执行模拟盘订单",
        symbol="R_75",
        amount=1,
        contract_type="CALL",
        duration=5,
        duration_unit="t",
        events=events,
    )
    assert report["ok"] is False
    assert report["reason"] == "missing_deriv_api_token"


def test_execution_requires_human_confirmation_before_write() -> None:
    st.session_state.deriv_token = "demo-token"
    st.session_state.require_trade_confirmation = True
    st.session_state.confirm_next_trade = False
    events: list[web_app.AgentEvent] = []

    report = web_app.execution_agent(
        task="执行模拟盘订单",
        symbol="R_75",
        amount=1,
        contract_type="CALL",
        duration=5,
        duration_unit="t",
        events=events,
    )

    assert report["ok"] is False
    assert report["reason"] == "pending_human_confirmation"
    assert st.session_state.pending_trade["action"] == "execute_simulated_trade"
    assert st.session_state.pending_trade["amount"] == 1.0


def test_closed_loop_trade_stops_at_human_confirmation(monkeypatch: Any) -> None:
    st.session_state.deriv_token = "demo-token"
    st.session_state.require_trade_confirmation = True
    st.session_state.confirm_next_trade = False

    def fake_call_deriv_tool(tool_name: str, coro: Any, params: dict[str, Any], writer: Any = None) -> dict[str, Any]:
        if inspect.iscoroutine(coro):
            coro.close()
        if tool_name == "get_market_ticks":
            return {
                "ok": True,
                "data": {"tick": {"symbol": "R_75", "quote": 100.0, "timestamp": "2026-06-05T10:00:00Z"}},
            }
        raise AssertionError("write tool should not be called before human confirmation")

    monkeypatch.setattr(web_app, "call_deriv_tool", fake_call_deriv_tool)
    result, _summary = web_app.execute_trade_closed_loop(
        web_app.ToolPlan(
            action="execute_simulated_trade",
            params={
                "symbol": "R_75",
                "amount": 1.0,
                "contract_type": "CALL",
                "duration": 5,
                "duration_unit": "t",
                "condition": None,
            },
            rationale="test",
        )
    )

    assert result["ok"] is False
    assert result["error"]["reason"] == "pending_human_confirmation"
    assert st.session_state.pending_trade["amount"] == 1.0


def test_pending_trade_summary_flags_advisor_direction_conflict() -> None:
    summary = web_app.pending_trade_summary(
        {
            "action": "execute_simulated_trade",
            "symbol": "R_75",
            "amount": 10,
            "contract_type": "CALL",
            "duration": 5,
            "duration_unit": "t",
            "allow_live": False,
        },
        {
            "symbol": "R_75",
            "stance": "PUT",
            "confidence": 0.8,
        },
        {"known_count": 2, "fresh_count": 2, "stale_count": 0},
    )

    assert summary["has_pending_trade"] is True
    assert summary["advisor_alignment"] == "direction_conflict"
    assert "direction_conflict" in summary["flags"]


def test_pending_trade_summary_marks_aligned_fresh_demo_trade() -> None:
    summary = web_app.pending_trade_summary(
        {
            "action": "execute_simulated_trade",
            "symbol": "R_75",
            "amount": 10,
            "contract_type": "CALL",
            "duration": 5,
            "duration_unit": "t",
            "allow_live": False,
        },
        {
            "symbol": "R_75",
            "stance": "CALL",
            "confidence": 0.8,
        },
        {"known_count": 3, "fresh_count": 3, "stale_count": 0},
    )

    assert summary["advisor_alignment"] == "aligned"
    assert summary["flags"] == []


def test_advisor_trade_draft_creates_pending_demo_trade_from_call() -> None:
    draft = web_app.advisor_trade_draft(
        {
            "symbol": "r_75",
            "stance": "CALL",
            "confidence": 0.72,
            "entry_price": 123.45,
            "created_at": "2026-06-05T10:00:00Z",
        },
        amount=2.5,
        duration=10,
        duration_unit="t",
    )

    assert draft["ok"] is True
    pending = draft["pending_trade"]
    assert pending["action"] == "execute_simulated_trade"
    assert pending["symbol"] == "R_75"
    assert pending["contract_type"] == "CALL"
    assert pending["amount"] == 2.5
    assert pending["duration"] == 10
    assert pending["duration_unit"] == "t"
    assert pending["source"] == "advisor_council"


def test_advisor_trade_draft_blocks_wait_and_invalid_amount() -> None:
    wait = web_app.advisor_trade_draft({"symbol": "R_75", "stance": "WAIT"}, amount=1)
    invalid_amount = web_app.advisor_trade_draft({"symbol": "R_75", "stance": "PUT"}, amount=0)

    assert wait["ok"] is False
    assert wait["reason"] == "advisor_wait"
    assert invalid_amount["ok"] is False
    assert invalid_amount["reason"] == "invalid_amount"


def test_execution_blocks_live_account_without_allow_live(monkeypatch: Any) -> None:
    st.session_state.deriv_token = "live-token"
    st.session_state.require_trade_confirmation = False
    st.session_state.confirm_next_trade = True
    st.session_state.allow_live_execution = False

    def fake_call_deriv_tool(tool_name: str, coro: Any, params: dict[str, Any], writer: Any = None) -> dict[str, Any]:
        if inspect.iscoroutine(coro):
            coro.close()
        if tool_name == "check_account_status":
            return {"ok": True, "data": {"account_type": "live"}}
        raise AssertionError("write tool should not be called for blocked live account")

    monkeypatch.setattr(web_app, "call_deriv_tool", fake_call_deriv_tool)
    events: list[web_app.AgentEvent] = []
    report = web_app.execution_agent(
        task="执行模拟盘订单",
        symbol="R_75",
        amount=1,
        contract_type="CALL",
        duration=5,
        duration_unit="t",
        events=events,
    )

    assert report["ok"] is False
    assert report["reason"] == "live_account_blocked"

