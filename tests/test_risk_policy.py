from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from risk_policy import evaluate_global_risk, get_risk_policy, update_risk_policy


def test_risk_policy_defaults_persist_and_validate(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"

    initial = get_risk_policy(db_path)
    updated = update_risk_policy(
        db_path,
        {
            "max_single_trade_amount": 0.75,
            "max_daily_trade_budget": 3.0,
            "max_total_trade_budget": 12.0,
        },
    )

    assert initial["policy"]["enabled"] is True
    assert updated["policy"]["max_single_trade_amount"] == 0.75
    assert get_risk_policy(db_path)["policy"]["max_total_trade_budget"] == 12.0
    with pytest.raises(ValueError, match="single-trade"):
        update_risk_policy(db_path, {"max_single_trade_amount": 4.0})


def test_global_risk_enforces_budget_usage_and_cooldown(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    get_risk_policy(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE global_risk_policy
            SET spent_today = 4.5, spent_total = 24.5, realized_pnl_today = -2,
                open_positions = 1, last_trade_at = ?
            WHERE id = 1
            """,
            (datetime.now(timezone.utc).isoformat(),),
        )

    result = evaluate_global_risk(db_path, action="execute_simulated_trade", amount=1)

    assert result["ok"] is False
    assert "daily_budget_exceeded" in result["blockers"]
    assert "daily_loss_limit_reached" in result["blockers"]
    assert "open_position_limit_reached" in result["blockers"]
    assert "trade_cooldown_active" in result["blockers"]


def test_disabled_protection_still_rejects_invalid_amount(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    update_risk_policy(db_path, {"enabled": False})
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE global_risk_policy SET realized_pnl_today = -99, open_positions = 99 WHERE id = 1"
        )

    allowed = evaluate_global_risk(db_path, action="execute_simulated_trade", amount=50)
    invalid = evaluate_global_risk(db_path, action="execute_simulated_trade", amount=0)

    assert allowed["ok"] is True
    assert allowed["blockers"] == []
    assert invalid["ok"] is False
    assert invalid["blockers"] == ["invalid_amount"]
