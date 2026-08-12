from __future__ import annotations

import inspect
import json
from typing import Any

import pytest
import streamlit as st

import server
import web_app


@pytest.fixture(autouse=True)
def reset_state() -> None:
    st.session_state.clear()
    web_app.init_state()


def test_three_layer_security_order_is_compliance_risk_execution() -> None:
    edges = {(item.source, item.target) for item in web_app.build_execution_langgraph().get_graph().edges}
    assert ("market", "compliance") in edges
    assert ("compliance", "risk") in edges
    assert ("risk", "chart") in edges
    assert ("chart", "safety_gate") in edges
    assert ("safety_gate", "execution") in edges
    assert ("risk", "compliance") not in edges
    assert ("compliance", "execution") not in edges


def test_human_confirmation_gate_prevents_any_account_or_write_call(monkeypatch: Any) -> None:
    st.session_state.deriv_token = "demo-secret-token"
    st.session_state.require_trade_confirmation = True
    st.session_state.confirm_next_trade = False
    monkeypatch.setattr(
        web_app,
        "call_deriv_tool",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("API called before HITL")),
    )
    report = web_app.execution_agent(
        task="执行模拟盘订单",
        symbol="R_100",
        amount=10,
        contract_type="CALL",
        duration=5,
        duration_unit="t",
        events=[],
    )
    assert report["reason"] == "pending_human_confirmation"


def test_live_default_gate_prevents_write_even_after_hitl(monkeypatch: Any) -> None:
    st.session_state.deriv_token = "live-secret-token"
    st.session_state.require_trade_confirmation = True
    st.session_state.confirm_next_trade = True
    assert st.session_state.allow_live_execution is False

    def fake_tool(name: str, coro: Any, params: dict[str, Any], writer: Any = None) -> dict[str, Any]:
        if inspect.iscoroutine(coro):
            coro.close()
        if name == "check_account_status":
            return {"ok": True, "data": {"account_type": "live"}}
        raise AssertionError("write API called for default-blocked live account")

    monkeypatch.setattr(web_app, "call_deriv_tool", fake_tool)
    report = web_app.execution_agent(
        task="执行订单",
        symbol="R_100",
        amount=10,
        contract_type="CALL",
        duration=5,
        duration_unit="t",
        events=[],
    )
    assert report["reason"] == "live_account_blocked"


def test_server_error_masks_token_from_exception() -> None:
    secret = "abc123-super-secret-xyz789"
    payload = json.loads(
        server.error_response(
            "fixture",
            RuntimeError(f"upstream echoed {secret}"),
            secrets=[secret],
        )
    )
    serialized = json.dumps(payload)
    assert secret not in serialized
    assert server.mask_secret(secret) in serialized


def test_recursive_trace_redaction_catches_nested_token_and_known_string() -> None:
    secret = "nested-secret-token"
    raw = {
        "api_token": secret,
        "nested": {"message": f"provider failed with {secret}", "secret": secret},
        "rows": [{"llm_api_key": secret}],
    }
    safe = web_app.redact_sensitive_values(raw, [secret])
    serialized = json.dumps(safe)
    assert secret not in serialized
    assert safe["api_token"] == "***"
    assert safe["nested"]["secret"] == "***"


def test_security_gate_source_contains_required_capabilities() -> None:
    # Anti-cheat capability gate: deleting a check from the implementation must
    # fail independently of fixture behavior.
    execution_source = inspect.getsource(web_app.execution_agent)
    backend_source = inspect.getsource(server.enforce_demo_or_explicit_live)
    assert "require_trade_confirmation" in execution_source
    assert "pending_human_confirmation" in execution_source
    assert "allow_live_execution" in execution_source
    assert "live_account_blocked" in execution_source
    assert "allow_live" in backend_source
    assert "Live account execution is blocked by default" in backend_source
    assert "mask_secret" in inspect.getsource(server.execute_simulated_trade)
