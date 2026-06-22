"""Persistent global risk policy shared by analysis and approval workflows."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from budget_guard import BudgetLimits, budget_guard_check


DEFAULT_POLICY = {
    "enabled": True,
    "max_single_trade_amount": 1.0,
    "max_daily_trade_budget": 5.0,
    "max_total_trade_budget": 25.0,
    "max_daily_loss": 2.0,
    "max_open_positions": 1,
    "cooldown_seconds": 60,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_risk_policy_db(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS global_risk_policy (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                policy_json TEXT NOT NULL,
                budget_day TEXT NOT NULL,
                spent_today REAL NOT NULL,
                spent_total REAL NOT NULL,
                realized_pnl_today REAL NOT NULL,
                open_positions INTEGER NOT NULL,
                last_trade_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO global_risk_policy (
                id, policy_json, budget_day, spent_today, spent_total,
                realized_pnl_today, open_positions, last_trade_at, updated_at
            ) VALUES (1, ?, ?, 0, 0, 0, 0, NULL, ?)
            """,
            (json.dumps(DEFAULT_POLICY), date.today().isoformat(), _now()),
        )


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    try:
        policy = json.loads(str(row["policy_json"]))
    except json.JSONDecodeError:
        policy = dict(DEFAULT_POLICY)
    merged = {**DEFAULT_POLICY, **(policy if isinstance(policy, dict) else {})}
    return {
        "policy": merged,
        "usage": {
            "budget_day": row["budget_day"],
            "spent_today": float(row["spent_today"]),
            "spent_total": float(row["spent_total"]),
            "realized_pnl_today": float(row["realized_pnl_today"]),
            "open_positions": int(row["open_positions"]),
            "last_trade_at": row["last_trade_at"],
        },
        "updated_at": row["updated_at"],
    }


def get_risk_policy(db_path: Path) -> dict[str, Any]:
    init_risk_policy_db(db_path)
    today = date.today().isoformat()
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM global_risk_policy WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("global risk policy is missing")
        if str(row["budget_day"]) != today:
            conn.execute(
                """
                UPDATE global_risk_policy
                SET budget_day = ?, spent_today = 0, realized_pnl_today = 0, updated_at = ?
                WHERE id = 1
                """,
                (today, _now()),
            )
            row = conn.execute("SELECT * FROM global_risk_policy WHERE id = 1").fetchone()
    return _decode(row)


def update_risk_policy(db_path: Path, policy: dict[str, Any]) -> dict[str, Any]:
    current = get_risk_policy(db_path)
    merged = {**current["policy"], **policy}
    if float(merged["max_single_trade_amount"]) > float(merged["max_daily_trade_budget"]):
        raise ValueError("single-trade limit cannot exceed daily budget")
    if float(merged["max_daily_trade_budget"]) > float(merged["max_total_trade_budget"]):
        raise ValueError("daily budget cannot exceed total budget")
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE global_risk_policy SET policy_json = ?, updated_at = ? WHERE id = 1",
            (json.dumps(merged, ensure_ascii=False), _now()),
        )
    return get_risk_policy(db_path)


def evaluate_global_risk(db_path: Path, *, action: str, amount: Any) -> dict[str, Any]:
    state = get_risk_policy(db_path)
    policy = state["policy"]
    usage = state["usage"]
    budget = budget_guard_check(
        action=action,
        amount=amount,
        limits=BudgetLimits(
            enabled=bool(policy["enabled"]),
            max_single_trade_amount=float(policy["max_single_trade_amount"]),
            max_daily_trade_budget=float(policy["max_daily_trade_budget"]),
            max_total_trade_budget=float(policy["max_total_trade_budget"]),
        ),
        daily_spent=float(usage["spent_today"]),
        total_spent=float(usage["spent_total"]),
    )
    blockers: list[str] = []
    if not budget.get("ok"):
        blockers.append(str(budget.get("reason") or "budget_blocked"))
    protection_enabled = bool(policy["enabled"])
    opens_position = action != "close_open_contract"
    if protection_enabled and opens_position:
        if float(usage["realized_pnl_today"]) <= -float(policy["max_daily_loss"]):
            blockers.append("daily_loss_limit_reached")
        if int(usage["open_positions"]) >= int(policy["max_open_positions"]):
            blockers.append("open_position_limit_reached")
        last_trade_at = usage.get("last_trade_at")
        if last_trade_at and int(policy["cooldown_seconds"]) > 0:
            try:
                last_trade = datetime.fromisoformat(str(last_trade_at).replace("Z", "+00:00"))
                elapsed = (datetime.now(timezone.utc) - last_trade.astimezone(timezone.utc)).total_seconds()
                if elapsed < int(policy["cooldown_seconds"]):
                    blockers.append("trade_cooldown_active")
            except ValueError:
                blockers.append("invalid_last_trade_timestamp")
    return {
        "ok": not blockers,
        "blockers": blockers,
        "budget": budget,
        "policy": policy,
        "usage": usage,
    }
