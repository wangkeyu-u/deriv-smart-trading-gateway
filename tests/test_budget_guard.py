from __future__ import annotations

from datetime import date

from budget_guard import BudgetLimits, budget_guard_check, record_budget_spend


def test_budget_guard_blocks_daily_and_total_caps() -> None:
    daily = budget_guard_check(
        action="execute_simulated_trade",
        amount=1,
        limits=BudgetLimits(max_single_trade_amount=1, max_daily_trade_budget=1.5, max_total_trade_budget=5),
        daily_spent=1,
        total_spent=1,
    )
    total = budget_guard_check(
        action="execute_simulated_trade",
        amount=1,
        limits=BudgetLimits(max_single_trade_amount=1, max_daily_trade_budget=5, max_total_trade_budget=1.5),
        daily_spent=0,
        total_spent=1,
    )

    assert daily["ok"] is False
    assert daily["reason"] == "daily_budget_exceeded"
    assert total["ok"] is False
    assert total["reason"] == "total_budget_exceeded"


def test_record_budget_spend_tracks_session_totals() -> None:
    state = {"budget_day": "2026-06-05", "budget_spent_today": 0.5, "budget_spent_total": 1.0}
    record_budget_spend(state, 0.75, today=date(2026, 6, 5))

    assert state["budget_spent_today"] == 1.25
    assert state["budget_spent_total"] == 1.75
