"""Exercise actual dispatch/transport boundaries without contacting Deriv."""
from __future__ import annotations

import asyncio
import inspect
import json

import pytest
import streamlit as st

import server
import web_app


@pytest.fixture(autouse=True)
def isolated_state():
    st.session_state.clear()
    web_app.init_state()


@pytest.mark.parametrize("status", [
    {"ok": False, "error": {"message": "authorization failed"}},
    {"ok": True, "data": {"account_type": "unknown"}},
])
def test_failed_account_check_cannot_reach_write(monkeypatch, status):
    st.session_state.deriv_token = "test-token"
    st.session_state.confirm_next_trade = True
    called = []

    def call(name, coro, params, writer=None):
        if inspect.iscoroutine(coro):
            coro.close()
        called.append(name)
        assert name == "check_account_status"
        return status

    monkeypatch.setattr(web_app, "call_deriv_tool", call)
    result = web_app.execution_agent(task="buy", symbol="R_75", amount=10,
                                    contract_type="CALL", duration=5, duration_unit="t", events=[])
    assert result["reason"] == "account_authorization_unverified"
    assert called == ["check_account_status"]


def test_unknown_account_rejected_even_with_live_flag():
    with pytest.raises(server.DerivAPIError, match="unverified"):
        server.enforce_demo_or_explicit_live({}, True)


@pytest.mark.parametrize("arguments", [[], "not an object", {}, None])
def test_malformed_model_tool_arguments_are_rejected_before_dispatch(monkeypatch, arguments):
    def unexpected(*args, **kwargs):
        raise AssertionError("malformed call must not dispatch")

    monkeypatch.setattr(web_app, "assign_task_to_execution_agent", unexpected)
    result = web_app.manager_tool_dispatch("assign_task_to_execution_agent", arguments, [])
    assert result["ok"] is False


@pytest.mark.parametrize("failure", ["invalid_symbol", "buy_timeout"])
def test_trade_transport_failure_never_retries_buy(monkeypatch, failure):
    calls = []

    class FakeClient:
        authorization = {"loginid": "VRTC123", "currency": "USD"}

        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, payload, **kwargs):
            calls.append((payload, kwargs))
            if "proposal" in payload:
                if failure == "invalid_symbol":
                    raise server.DerivAPIError("Invalid symbol")
                return {"proposal": {"id": "proposal-1", "ask_price": 10}}
            assert kwargs["retries"] == 0
            raise server.DerivTimeoutError("Write outcome unknown")

    monkeypatch.setattr(server, "DerivWebSocketClient", FakeClient)
    result = json.loads(asyncio.run(server.execute_simulated_trade(
        "test-token", "INVALID" if failure == "invalid_symbol" else "R_75",
        10.0, "CALL", 5, "t")))
    assert result["ok"] is False
    buys = [payload for payload, _ in calls if "buy" in payload]
    assert len(buys) == (0 if failure == "invalid_symbol" else 1)


def test_one_advisor_failure_falls_back_without_executing_trade(monkeypatch):
    original = web_app.local_advisor_opinion
    failed = False

    def flaky(advisor, *args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("injected one-node failure")
        return original(advisor, *args, **kwargs)

    def forbidden_write(*args, **kwargs):
        raise AssertionError("an advisory fallback must not trade")

    monkeypatch.setattr(web_app, "local_advisor_opinion", flaky)
    monkeypatch.setattr(web_app, "collect_advisor_web_context", lambda *a, **k: [])
    monkeypatch.setattr(web_app, "advisor_market_snapshot", lambda *a, **k: {
        "symbol": "R_75", "summary": "synthetic market", "trend": "up", "latest_close": 100.0})
    monkeypatch.setattr(web_app, "advisor_llm_synthesis", lambda *a, **k: None)
    monkeypatch.setattr(web_app, "save_advisor_run", lambda *a, **k: None)
    monkeypatch.setattr(web_app, "execute_simulated_trade", forbidden_write)
    result = web_app.run_advisor_council("inspect R_75", "R_75", 4, False)
    assert failed
    assert result["runtime"] == "local_fallback"
    assert result["opinions"]
