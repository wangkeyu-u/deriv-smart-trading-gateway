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
    staged = web_app.execution_agent(task="buy", symbol="R_75", amount=10,
                                     contract_type="CALL", duration=5, duration_unit="t", events=[])
    assert staged["reason"] == "pending_human_confirmation"
    st.session_state.confirm_next_trade = True
    called=[]
    original=web_app.trading_application
    def factory(*args,**kwargs):
        service=original(*args,**kwargs)
        async def account():
            called.append('account')
            raise server.DerivAPIError('Unverified authorization')
        service.adapter.get_account=account
        return service
    monkeypatch.setattr(web_app,'trading_application',factory)
    result=web_app.execution_agent(task='buy',symbol='R_75',amount=10,contract_type='CALL',duration=5,duration_unit='t',events=[])
    assert result['reason']=='account_authorization_unverified'
    assert called==['account']


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
    from services.context import ExecutionContext
    from adapters.deriv.websocket import WebSocketDerivAdapter
    from domain.trade import TradeIntent
    from decimal import Decimal
    from execution.engine import UnknownOutcomeError
    from domain.order import Order
    intent=TradeIntent(action='BUY',symbol='INVALID' if failure=='invalid_symbol' else 'R_75',direction='CALL',
        amount=Decimal('10'),duration=5,duration_unit='t',account_mode='demo',source='streamlit')
    adapter=WebSocketDerivAdapter('test-token',FakeClient,ExecutionContext('streamlit'))
    if failure=='invalid_symbol':
        with pytest.raises(server.DerivAPIError):
            asyncio.run(adapter.get_proposal(intent))
    else:
        proposal=asyncio.run(adapter.get_proposal(intent))
        order=Order(intent_id=intent.intent_id,idempotency_key='key',account_id='VRTC123',action=intent.action,
            symbol=intent.symbol,direction=intent.direction,amount=intent.amount,proposal_id=proposal.proposal_id)
        with pytest.raises(UnknownOutcomeError):
            asyncio.run(adapter.place_order(intent,order))
    buys = [payload for payload, _ in calls if "buy" in payload]
    assert len(buys) == (0 if failure == "invalid_symbol" else 1)


def test_one_advisor_failure_does_not_restart_or_execute_trade(monkeypatch):
    original = web_app.local_advisor_opinion
    failed = False
    market_calls = []

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
    monkeypatch.setattr(web_app, "advisor_market_snapshot", lambda *a, **k: market_calls.append(1) or {
        "symbol": "R_75", "summary": "synthetic market", "trend": "up", "latest_close": 100.0})
    monkeypatch.setattr(web_app, "advisor_llm_synthesis", lambda *a, **k: None)
    monkeypatch.setattr(web_app, "save_advisor_run", lambda *a, **k: None)
    monkeypatch.setattr(web_app, "place_contract", forbidden_write)
    result = web_app.run_advisor_council("inspect R_75", "R_75", 4, False)
    assert failed
    assert result["runtime"] == "langgraph"
    assert result["ok"] is False
    assert result["status"] == "error"
    assert result["stance"] == "WAIT"
    assert market_calls == [1]
