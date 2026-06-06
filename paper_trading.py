"""Paper trading and circuit-breaker utilities for the micro strategy module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import math

import pandas as pd

from micro_trading import MicroTradeConfig, analyze_micro_trade, normalize_price_frame


@dataclass(frozen=True)
class CircuitBreakerConfig:
    max_consecutive_losses: int = 3
    max_total_loss_amount: float = 2.0
    max_drawdown_pct: float = 3.0
    max_trade_count: int = 30


def action_is_trade(action: str) -> bool:
    return action in {"CALL", "PUT", "BUY", "SELL"}


def paper_trade_return_pct(action: str, entry_price: float, exit_price: float) -> float:
    if not entry_price or not math.isfinite(entry_price):
        return 0.0
    raw = (exit_price - entry_price) / entry_price * 100
    if action in {"PUT", "SELL"}:
        raw *= -1
    if action not in {"CALL", "PUT", "BUY", "SELL"}:
        raw = 0.0
    return round(raw, 5)


def paper_trade_pnl(action: str, entry_price: float, exit_price: float, amount: float) -> float:
    return round(float(amount) * paper_trade_return_pct(action, entry_price, exit_price) / 100, 8)


def evaluate_circuit_breaker(
    trades: list[dict[str, Any]],
    config: CircuitBreakerConfig,
) -> dict[str, Any]:
    if not trades:
        return {"halted": False, "reason": None, "consecutive_losses": 0, "drawdown_pct": 0.0}
    consecutive_losses = 0
    for trade in reversed(trades):
        if float(trade.get("pnl") or 0.0) < 0:
            consecutive_losses += 1
        else:
            break

    equity_values = [float(item.get("equity") or 0.0) for item in trades]
    peak = max(equity_values) if equity_values else 0.0
    current = equity_values[-1] if equity_values else 0.0
    drawdown_pct = round((peak - current) / peak * 100, 5) if peak > 0 else 0.0
    total_loss = abs(sum(float(item.get("pnl") or 0.0) for item in trades if float(item.get("pnl") or 0.0) < 0))

    reason = None
    if consecutive_losses >= config.max_consecutive_losses:
        reason = "max_consecutive_losses"
    elif total_loss >= config.max_total_loss_amount:
        reason = "max_total_loss_amount"
    elif drawdown_pct >= config.max_drawdown_pct:
        reason = "max_drawdown_pct"
    elif len(trades) >= config.max_trade_count:
        reason = "max_trade_count"

    return {
        "halted": reason is not None,
        "reason": reason,
        "consecutive_losses": consecutive_losses,
        "drawdown_pct": drawdown_pct,
        "total_loss_amount": round(total_loss, 8),
        "trade_count": len(trades),
    }


def backtest_micro_strategy(
    prices: pd.DataFrame | list[dict[str, Any]],
    strategy_config: MicroTradeConfig,
    circuit_config: CircuitBreakerConfig | None = None,
    *,
    lookback_bars: int = 12,
    exit_after_bars: int = 1,
) -> dict[str, Any]:
    frame = normalize_price_frame(prices)
    if len(frame) < max(lookback_bars + exit_after_bars, 9):
        return {
            "ok": False,
            "reason": "insufficient_price_history",
            "bars": len(frame),
            "trades": [],
            "summary": {},
        }

    circuit = circuit_config or CircuitBreakerConfig()
    trades: list[dict[str, Any]] = []
    equity = 100.0
    halted = {"halted": False, "reason": None}

    for idx in range(lookback_bars, len(frame) - exit_after_bars):
        window = frame.iloc[idx - lookback_bars : idx + 1]
        decision = analyze_micro_trade(window, strategy_config)
        action = str(decision.get("action") or "")
        if not action_is_trade(action):
            continue
        entry = float(frame.iloc[idx]["close"])
        exit_price = float(frame.iloc[idx + exit_after_bars]["close"])
        pnl = paper_trade_pnl(action, entry, exit_price, strategy_config.max_trade_amount)
        equity = round(equity + pnl, 8)
        trade = {
            "index": idx,
            "action": action,
            "entry_price": entry,
            "exit_price": exit_price,
            "amount": strategy_config.max_trade_amount,
            "return_pct": paper_trade_return_pct(action, entry, exit_price),
            "pnl": pnl,
            "equity": equity,
            "confidence": decision.get("confidence"),
            "blockers": decision.get("blockers") or [],
        }
        trades.append(trade)
        halted = evaluate_circuit_breaker(trades, circuit)
        if halted["halted"]:
            break

    wins = [item for item in trades if float(item.get("pnl") or 0.0) > 0]
    losses = [item for item in trades if float(item.get("pnl") or 0.0) < 0]
    total_pnl = round(sum(float(item.get("pnl") or 0.0) for item in trades), 8)
    summary = {
        "trade_count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades), 4) if trades else None,
        "total_pnl": total_pnl,
        "ending_equity": round(equity, 8),
        "average_pnl": round(total_pnl / len(trades), 8) if trades else None,
        "halted": halted.get("halted", False),
        "halt_reason": halted.get("reason"),
        "drawdown_pct": halted.get("drawdown_pct", 0.0),
    }
    return {
        "ok": True,
        "symbol": strategy_config.symbol,
        "asset_kind": strategy_config.asset_kind,
        "bars": len(frame),
        "summary": summary,
        "circuit_breaker": halted,
        "trades": trades,
    }
