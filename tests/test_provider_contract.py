from __future__ import annotations

from typing import Any

import pytest
import streamlit as st

import web_app


PROVIDERS = ["OpenAI", "Anthropic", "DeepSeek"]


@pytest.fixture(autouse=True)
def reset_state() -> None:
    st.session_state.clear()
    web_app.init_state()


@pytest.mark.parametrize("provider", PROVIDERS)
def test_mock_provider_uses_one_tool_contract_then_same_graph(
    provider: web_app.ToolCallingProvider,
    monkeypatch: Any,
) -> None:
    seen: list[tuple[str, str]] = []

    def fixture_invoker(name: web_app.ToolCallingProvider, text: str) -> list[dict[str, Any]]:
        seen.append((name, text))
        return [
            {
                "name": "assign_task_to_strategy_agent",
                "arguments": {"task": text, "symbol": "R_100"},
            }
        ]

    sentinel = web_app.TeamRunResult(
        "fixture graph",
        [],
        runtime_evidence={"runtime": "langgraph", "fixture": True},
    )
    monkeypatch.setattr(web_app, "run_execution_langgraph", lambda *args, **kwargs: sentinel)
    result = web_app.run_provider_to_deterministic_graph(
        provider,
        "fixture request",
        provider_invoker=fixture_invoker,
    )
    evidence = result.runtime_evidence or {}
    assert seen == [(provider, "fixture request")]
    assert evidence["provider_status"] == "tool_calls_received"
    assert evidence["provider_tool_contract_count"] == len(web_app.MANAGER_TOOLS) == 7
    assert evidence["business_runtime"] == "deterministic_langgraph_python"
    assert evidence["fixture"] is True


@pytest.mark.parametrize("provider", PROVIDERS)
def test_mock_provider_failure_falls_back_to_same_deterministic_graph(
    provider: web_app.ToolCallingProvider,
    monkeypatch: Any,
) -> None:
    secret = "provider-secret-token"
    st.session_state.llm_api_key = secret
    sentinel = web_app.TeamRunResult("fallback graph", [], runtime_evidence={"runtime": "langgraph"})
    monkeypatch.setattr(web_app, "run_execution_langgraph", lambda *args, **kwargs: sentinel)

    def failing_invoker(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError(f"fixture provider failed with {secret}")

    result = web_app.run_provider_to_deterministic_graph(
        provider,
        "fixture request",
        provider_invoker=failing_invoker,
    )
    evidence = result.runtime_evidence or {}
    assert evidence["provider_status"] == "deterministic_fallback"
    assert evidence["business_runtime"] == "deterministic_langgraph_python"
    assert secret not in evidence["provider_error"]
    assert "pro***ken" in evidence["provider_error"]


def test_unknown_provider_tool_is_rejected_before_graph_dispatch() -> None:
    with pytest.raises(ValueError, match="unknown manager tool"):
        web_app.validate_manager_tool_calls(
            [{"name": "execute_simulated_trade", "arguments": {}}]
        )
