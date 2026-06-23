"""Case evidence persistence helpers.

Extracted from gateway_api.py so that the evidence-persistence
logic lives in one place and can be tested independently.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from trade_cases import get_trade_case, record_trade_case_artifact


def _case_summary(case: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal case summary dict."""
    return {
        "id": case["id"],
        "title": case.get("title", ""),
        "symbol": case["symbol"],
        "status": case["status"],
        "stage": case["stage"],
        "version": case["version"],
    }


def _case_updated_event(case: dict[str, Any]) -> dict[str, Any]:
    """Build an event payload for a case update."""
    return {
        "case_id": case["id"],
        "title": case.get("title", ""),
        "symbol": case["symbol"],
        "status": case["status"],
        "stage": case["stage"],
        "version": case["version"],
        "updated_at": case.get("updated_at", ""),
    }


def _decision_inbox_item(case: dict[str, Any]) -> dict[str, Any]:
    """Build a decision inbox item from a case dict."""
    policy = case.get("policy_snapshot") or {}
    risk = case.get("risk_context") or {}
    evidence = case.get("latest_evidence") or {}
    return {
        "case": _case_summary(case),
        "decision": case.get("latest_decision") or {},
        "state": _infer_decision_state(case),
        "evidence_score": float(evidence.get("confidence", 0)),
        "blockers": policy.get("blockers", []),
        "global_risk": risk.get("policy", {}),
    }


def _infer_decision_state(case: dict[str, Any]) -> str:
    """Infer the decision state from case status/stage."""
    status = case.get("status", "")
    stage = case.get("stage", "")
    if status == "completed":
        return "approved"
    if status == "cancelled":
        return "rejected"
    if stage in ("evidence", "review"):
        return "ready"
    if stage == "blocked":
        return "blocked"
    return "evidence_requested"


def _direction_from_answer(answer: str, broker_id: str = "deriv") -> str:
    """Extract a trade direction (CALL/PUT/BUY/SELL) from an advisor answer."""
    answer_upper = answer.upper()
    for keyword in ("CALL", "BUY"):
        if keyword in answer_upper:
            return "CALL"
    for keyword in ("PUT", "SELL"):
        if keyword in answer_upper:
            return "PUT"
    return "HOLD"


def _market_artifact(market: dict[str, Any], symbol: str) -> dict[str, Any]:
    """Build a market artifact payload."""
    return {
        "symbol": symbol,
        "window_change_pct": market.get("window_change_pct"),
        "latest_close": market.get("latest_close"),
        "candle_count": market.get("candle_count", 0),
        "ok": market.get("ok", False),
    }


def persist_chat_case_evidence(
    *,
    linked_case: dict[str, Any],
    question: str,
    answer: str,
    reports: dict[str, dict[str, str]],
    market: dict[str, Any] | None,
    route: list[str],
    session_id: str,
    provider: str,
    model: str,
) -> list[dict[str, Any]]:
    """Persist chat-derived evidence (advisor, market, risk, workflow) to a trade case.

    Returns a list of event dicts suitable for SSE streaming.
    """
    case_id = str(linked_case["id"])
    symbol = str(linked_case["symbol"])
    broker_id = str(linked_case.get("broker_id") or "deriv")
    stance = _direction_from_answer(answer, broker_id)
    updated: list[dict[str, Any]] = []

    # 1. Advisor artifact
    advisor_case = _record_case_artifact(
        case_id,
        artifact_type="advisor",
        actor="advisor_council",
        message="谋士团结论已从经理对话同步",
        payload={
            "question": question,
            "symbol": symbol,
            "broker_id": broker_id,
            "stance": stance,
            "confidence": 0.68 if stance in {"CALL", "PUT", "BUY", "SELL"} else 0.45,
            "consensus": answer,
            "reports": reports,
            "route": route,
            "session_id": session_id,
            "provider": provider,
            "model": model,
        },
    )
    updated.append(_case_updated_event(advisor_case))

    # 2. Market artifact (if available)
    completed_steps = ["manager_dispatch", "advisor_review"]
    if market is not None:
        market_case = _record_case_artifact(
            case_id,
            artifact_type="market",
            actor="market_agent",
            message="行情快照已同步到交易任务",
            payload=_market_artifact(market, symbol),
        )
        updated.append(_case_updated_event(market_case))
        completed_steps.append("market_validation")

    # 3. Risk artifact (always recorded)
    blockers = ["analysis_only", "micro_strategy_not_run", "human_confirmation_required"]
    if market is None:
        blockers.append("market_snapshot_not_run")
    risk_case = _record_case_artifact(
        case_id,
        artifact_type="risk",
        actor="risk_agent",
        message="风控 Agent 已记录剩余前置条件",
        payload={
            "ok": False,
            "blockers": blockers,
            "warnings": ["No order draft was created from chat"],
            "symbol": symbol,
            "broker_id": broker_id,
            "session_id": session_id,
        },
        advance_stage=False,
    )
    updated.append(_case_updated_event(risk_case))

    # 4. Workflow artifact
    workflow_case = _record_case_artifact(
        case_id,
        artifact_type="workflow_run",
        actor="manager",
        message="本轮分析完成，下一步进入小笔策略纸面回测",
        payload={
            "status": "analysis_complete",
            "current_step": "micro_backtest",
            "completed_steps": completed_steps,
            "session_id": session_id,
            "broker_id": broker_id,
        },
    )
    updated.append(_case_updated_event(workflow_case))

    return updated


def _record_case_artifact(
    case_id: str,
    *,
    artifact_type: str,
    actor: str,
    message: str,
    payload: dict[str, Any],
    advance_stage: bool = True,
) -> dict[str, Any]:
    """Delegate to trade_cases.record_trade_case_artifact."""
    return record_trade_case_artifact(
        case_id=case_id,
        artifact_type=artifact_type,
        actor=actor,
        message=message,
        payload=payload,
        advance_stage=advance_stage,
    )
