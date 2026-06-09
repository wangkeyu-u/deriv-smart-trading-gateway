"""Hard budget guard for trade execution.

The guard treats trade amount as committed spend before an order is submitted.
It is deliberately simple and deterministic so every write path can apply the
same limits before reaching broker/tool execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import math


@dataclass(frozen=True)
class BudgetLimits:
    enabled: bool = True
    max_single_trade_amount: float = 1.0
    max_daily_trade_budget: float = 5.0
    max_total_trade_budget: float = 5.0


def normalize_trade_amount(value: Any) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(amount):
        return 0.0
    return round(amount, 8)


def budget_guard_check(
    *,
    action: str,
    amount: Any,
    limits: BudgetLimits,
    daily_spent: float = 0.0,
    total_spent: float = 0.0,
) -> dict[str, Any]:
    if action == "close_open_contract":
        return {
            "ok": True,
            "reason": "close_has_no_new_stake",
            "amount": 0.0,
            "remaining_daily": max(0.0, limits.max_daily_trade_budget - daily_spent),
            "remaining_total": max(0.0, limits.max_total_trade_budget - total_spent),
        }
    amount_value = normalize_trade_amount(amount)
    if not limits.enabled:
        return {
            "ok": amount_value > 0,
            "reason": "budget_guard_disabled" if amount_value > 0 else "invalid_amount",
            "amount": amount_value,
            "remaining_daily": None,
            "remaining_total": None,
        }
    if amount_value <= 0:
        return {"ok": False, "reason": "invalid_amount", "amount": amount_value}
    if amount_value > limits.max_single_trade_amount:
        return {
            "ok": False,
            "reason": "single_trade_limit_exceeded",
            "amount": amount_value,
            "limit": limits.max_single_trade_amount,
        }
    if daily_spent + amount_value > limits.max_daily_trade_budget:
        return {
            "ok": False,
            "reason": "daily_budget_exceeded",
            "amount": amount_value,
            "spent": round(daily_spent, 8),
            "limit": limits.max_daily_trade_budget,
        }
    if total_spent + amount_value > limits.max_total_trade_budget:
        return {
            "ok": False,
            "reason": "total_budget_exceeded",
            "amount": amount_value,
            "spent": round(total_spent, 8),
            "limit": limits.max_total_trade_budget,
        }
    return {
        "ok": True,
        "reason": "within_budget",
        "amount": amount_value,
        "remaining_daily": round(limits.max_daily_trade_budget - daily_spent - amount_value, 8),
        "remaining_total": round(limits.max_total_trade_budget - total_spent - amount_value, 8),
    }


def reset_daily_spend_if_needed(state: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    current = today or date.today()
    stored_day = str(state.get("budget_day") or "")
    if stored_day != current.isoformat():
        state["budget_day"] = current.isoformat()
        state["budget_spent_today"] = 0.0
    return state


def record_budget_spend(state: dict[str, Any], amount: Any, *, today: date | None = None) -> dict[str, Any]:
    reset_daily_spend_if_needed(state, today=today)
    amount_value = normalize_trade_amount(amount)
    state["budget_spent_today"] = round(float(state.get("budget_spent_today") or 0.0) + amount_value, 8)
    state["budget_spent_total"] = round(float(state.get("budget_spent_total") or 0.0) + amount_value, 8)
    return state
