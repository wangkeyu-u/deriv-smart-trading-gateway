"""Deterministic checks for the automated Trade Case workflow."""

from __future__ import annotations

from typing import Any


WORKFLOW_STEPS = (
    "advisor",
    "market",
    "micro_strategy",
    "consistency_gate",
    "human_confirmation",
)

BLOCKER_MESSAGES = {
    "missing_advisor": "Advisor evidence is missing.",
    "advisor_not_actionable": "Advisor stance is WAIT or invalid.",
    "missing_market": "Market evidence is missing.",
    "market_data_unhealthy": "Market data integrity or freshness failed.",
    "missing_micro_strategy": "Micro-strategy evidence is missing.",
    "micro_not_actionable": "Micro strategy did not produce CALL or PUT.",
    "budget_blocked": "The configured budget guard rejected the proposal.",
    "backtest_halted": "The paper backtest triggered a circuit breaker.",
    "no_paper_trades": "The paper backtest produced no trades.",
    "missing_trade_draft": "No executable trade draft was produced.",
    "symbol_mismatch": "Artifacts do not reference the same symbol.",
    "direction_conflict": "Advisor, strategy, and trade draft directions conflict.",
    "invalid_amount": "Trade amount is invalid or exceeds the strategy limit.",
    "live_execution": "One-click simulation cannot prepare a live-account order.",
}


def _artifact_payload(case: dict[str, Any], artifact_type: str) -> dict[str, Any]:
    artifacts = ((case.get("context") or {}).get("artifacts") or {})
    artifact = artifacts.get(artifact_type) or {}
    payload = artifact.get("payload") or {}
    return payload if isinstance(payload, dict) else {}


def _symbol(value: Any) -> str:
    return str(value or "").strip().casefold()


def _action(value: Any) -> str:
    return str(value or "").strip().upper()


def trade_case_consistency_gate(
    case: dict[str, Any],
    *,
    advisor: dict[str, Any] | None,
    market: dict[str, Any] | None,
    micro: dict[str, Any] | None,
    pending_trade: dict[str, Any] | None,
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    expected_symbol = _symbol(case.get("symbol"))

    if not advisor:
        blockers.append("missing_advisor")
        advisor_action = ""
    else:
        advisor_action = _action(advisor.get("stance"))
        if advisor_action not in {"CALL", "PUT"}:
            blockers.append("advisor_not_actionable")
        if _symbol(advisor.get("symbol")) != expected_symbol:
            blockers.append("symbol_mismatch")

    if not market:
        blockers.append("missing_market")
    else:
        if _symbol(market.get("symbol")) != expected_symbol:
            blockers.append("symbol_mismatch")
        integrity = market.get("integrity") or {}
        if not integrity.get("ok") or not integrity.get("fresh"):
            blockers.append("market_data_unhealthy")
        if int(market.get("candle_count") or 0) < 20:
            blockers.append("market_data_unhealthy")

    decision = (micro or {}).get("decision") or {}
    budget = (micro or {}).get("budget_guard") or {}
    backtest = (micro or {}).get("backtest") or {}
    summary = backtest.get("summary") or {}
    micro_action = _action(decision.get("action"))
    if not micro:
        blockers.append("missing_micro_strategy")
    else:
        config = micro.get("config") or {}
        if _symbol(config.get("symbol")) != expected_symbol:
            blockers.append("symbol_mismatch")
        if micro_action not in {"CALL", "PUT"}:
            blockers.append("micro_not_actionable")
        if not budget.get("ok"):
            blockers.append("budget_blocked")
        halt_reason = str(summary.get("halt_reason") or "")
        if summary.get("halted") and halt_reason != "max_trade_count":
            blockers.append("backtest_halted")
        if int(summary.get("trade_count") or 0) <= 0:
            blockers.append("no_paper_trades")

    if not pending_trade:
        if advisor_action in {"CALL", "PUT"}:
            blockers.append("missing_trade_draft")
        pending_action = ""
    else:
        pending_action = _action(pending_trade.get("contract_type"))
        if _symbol(pending_trade.get("symbol")) != expected_symbol:
            blockers.append("symbol_mismatch")
        if pending_trade.get("allow_live"):
            blockers.append("live_execution")
        try:
            amount = float(pending_trade.get("amount") or 0)
            max_amount = float(((micro or {}).get("config") or {}).get("max_trade_amount") or 0)
        except (TypeError, ValueError):
            amount = 0
            max_amount = 0
        if amount <= 0 or max_amount <= 0 or amount > max_amount:
            blockers.append("invalid_amount")

    actionable = [
        action
        for action in (advisor_action, micro_action, pending_action)
        if action in {"CALL", "PUT"}
    ]
    if actionable and len(set(actionable)) > 1:
        blockers.append("direction_conflict")

    unique_blockers = list(dict.fromkeys(blockers))
    if advisor and float(advisor.get("confidence") or 0) < 0.58:
        warnings.append("advisor_low_confidence")
    win_rate = summary.get("win_rate")
    if win_rate is not None and float(win_rate) < 0.5:
        warnings.append("paper_win_rate_below_50pct")
    if str(summary.get("halt_reason") or "") == "max_trade_count":
        warnings.append("paper_trade_cap_reached")

    return {
        "ok": not unique_blockers,
        "blockers": unique_blockers,
        "blocker_messages": [BLOCKER_MESSAGES.get(code, code) for code in unique_blockers],
        "warnings": warnings,
        "expected_symbol": case.get("symbol"),
        "advisor_action": advisor_action or None,
        "micro_action": micro_action or None,
        "pending_action": pending_action or None,
        "paper_trade_count": int(summary.get("trade_count") or 0),
        "paper_win_rate": summary.get("win_rate"),
        "paper_pnl": float(summary.get("total_pnl") or 0),
    }


def workflow_resume_step(case: dict[str, Any]) -> str:
    workflow = (((case.get("context") or {}).get("artifacts") or {}).get("workflow_run") or {}).get("payload") or {}
    failed_step = str(workflow.get("failed_step") or "")
    if failed_step in WORKFLOW_STEPS:
        return failed_step
    completed = set(workflow.get("completed_steps") or [])
    for step in WORKFLOW_STEPS:
        if step not in completed:
            return step
    return "human_confirmation"


def trade_case_decision_snapshot(case: dict[str, Any]) -> dict[str, Any]:
    """Build a stable operator-facing snapshot from persisted case artifacts."""
    advisor = _artifact_payload(case, "advisor")
    market = _artifact_payload(case, "market")
    micro = _artifact_payload(case, "micro_strategy")
    risk = _artifact_payload(case, "risk")
    workflow = _artifact_payload(case, "workflow_run")
    pending = _artifact_payload(case, "pending_trade")

    decision = micro.get("decision") or {}
    budget = micro.get("budget_guard") or {}
    paper = (micro.get("backtest") or {}).get("summary") or {}
    integrity = market.get("integrity") or {}
    workflow_status = str(workflow.get("status") or "")
    case_status = str(case.get("status") or "active")
    if case_status in {"failed", "cancelled", "completed", "paused"}:
        status = case_status
    elif workflow_status in {"blocked", "running", "awaiting_confirmation", "failed"}:
        status = workflow_status
    elif advisor or market or micro:
        status = "in_progress"
    else:
        status = "not_started"

    return {
        "case_id": case.get("id"),
        "case_status": case_status,
        "status": status,
        "symbol": case.get("symbol"),
        "stage": case.get("stage"),
        "retry_step": workflow.get("failed_step"),
        "workflow_step": workflow.get("current_step"),
        "advisor": {
            "action": _action(advisor.get("stance")) or None,
            "confidence": advisor.get("confidence"),
            "consensus": advisor.get("consensus"),
        },
        "market": {
            "latest_close": market.get("latest_close"),
            "latest_timestamp": market.get("latest_timestamp"),
            "candle_count": int(market.get("candle_count") or 0),
            "healthy": bool(integrity.get("ok")),
            "fresh": bool(integrity.get("fresh")),
            "issues": list(integrity.get("issues") or []),
        },
        "strategy": {
            "action": _action(decision.get("action")) or None,
            "confidence": decision.get("confidence"),
            "budget_ok": budget.get("ok"),
            "budget_reason": budget.get("reason"),
        },
        "paper": {
            "trade_count": int(paper.get("trade_count") or 0),
            "wins": int(paper.get("wins") or 0),
            "losses": int(paper.get("losses") or 0),
            "win_rate": paper.get("win_rate"),
            "total_pnl": float(paper.get("total_pnl") or 0),
            "halted": bool(paper.get("halted")),
            "halt_reason": paper.get("halt_reason"),
        },
        "gate": {
            "ok": risk.get("ok"),
            "blockers": list(risk.get("blockers") or (workflow.get("detail") or {}).get("blockers") or []),
            "warnings": list(risk.get("warnings") or (workflow.get("detail") or {}).get("warnings") or []),
        },
        "pending": {
            "exists": bool(pending),
            "action": _action(pending.get("contract_type")) or None,
            "amount": pending.get("amount"),
            "duration": pending.get("duration"),
            "duration_unit": pending.get("duration_unit"),
            "allow_live": bool(pending.get("allow_live")),
        },
    }
