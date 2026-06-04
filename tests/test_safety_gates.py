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
        amount=10,
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
        amount=10,
        contract_type="CALL",
        duration=5,
        duration_unit="t",
        events=events,
    )

    assert report["ok"] is False
    assert report["reason"] == "pending_human_confirmation"
    assert st.session_state.pending_trade["action"] == "execute_simulated_trade"


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
        amount=10,
        contract_type="CALL",
        duration=5,
        duration_unit="t",
        events=events,
    )

    assert report["ok"] is False
    assert report["reason"] == "live_account_blocked"
