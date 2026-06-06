"""Fast small-trade strategy engine.

This module is intentionally UI-agnostic. It produces a decision and risk
context from recent prices, but does not submit orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import math

import pandas as pd


AssetKind = Literal["deriv", "fund", "equity", "crypto", "forex"]
DerivAction = Literal["CALL", "PUT", "WAIT"]
SpotAction = Literal["BUY", "SELL", "HOLD"]
MicroAction = DerivAction | SpotAction


@dataclass(frozen=True)
class MicroTradeConfig:
    symbol: str
    asset_kind: AssetKind = "deriv"
    cadence_seconds: int = 30
    max_trade_amount: float = 1.0
    min_confidence: float = 0.58
    max_volatility_pct: float = 2.8
    min_momentum_pct: float = 0.03
    fee_bps: float = 0.0
    slippage_bps: float = 1.0
    cooldown_seconds: int = 60
    max_daily_loss_pct: float = 2.0


def normalize_price_frame(prices: pd.DataFrame | list[dict[str, Any]]) -> pd.DataFrame:
    frame = prices.copy() if isinstance(prices, pd.DataFrame) else pd.DataFrame(prices)
    if frame.empty or "close" not in frame.columns:
        return pd.DataFrame(columns=["close"])
    frame = frame.copy()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["close"])
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        frame = frame.sort_values("timestamp")
    return frame.reset_index(drop=True)


def _pct_change(start: float, end: float) -> float:
    if not start or not math.isfinite(start):
        return 0.0
    return (end - start) / start * 100


def _realized_volatility_pct(closes: pd.Series, periods: int = 12) -> float:
    returns = closes.pct_change().dropna().tail(periods)
    if returns.empty:
        return 0.0
    return float(returns.std(ddof=0) * math.sqrt(max(len(returns), 1)) * 100)


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _clip_confidence(value: float) -> float:
    return round(max(0.0, min(0.95, value)), 3)


def _directional_action(asset_kind: AssetKind, direction: str) -> MicroAction:
    if asset_kind == "deriv":
        return "CALL" if direction == "up" else "PUT"
    return "BUY" if direction == "up" else "SELL"


def _neutral_action(asset_kind: AssetKind) -> MicroAction:
    return "WAIT" if asset_kind == "deriv" else "HOLD"


def analyze_micro_trade(
    prices: pd.DataFrame | list[dict[str, Any]],
    config: MicroTradeConfig,
) -> dict[str, Any]:
    frame = normalize_price_frame(prices)
    if len(frame) < 8:
        return {
            "ok": False,
            "action": _neutral_action(config.asset_kind),
            "confidence": 0.0,
            "reason": "insufficient_price_history",
            "required_bars": 8,
            "bars": len(frame),
        }

    closes = frame["close"]
    latest = float(closes.iloc[-1])
    previous = float(closes.iloc[-2])
    short_ema = _ema(closes, 4)
    long_ema = _ema(closes, 12)
    short_latest = float(short_ema.iloc[-1])
    long_latest = float(long_ema.iloc[-1])
    momentum_3 = _pct_change(float(closes.iloc[-4]), latest)
    momentum_7 = _pct_change(float(closes.iloc[-8]), latest)
    tick_delta = _pct_change(previous, latest)
    volatility = _realized_volatility_pct(closes)
    gross_edge = abs(momentum_3) - ((config.fee_bps + config.slippage_bps) / 100)

    direction = "up" if short_latest >= long_latest and momentum_3 > 0 else "down"
    if short_latest < long_latest and momentum_3 < 0:
        direction = "down"
    elif abs(momentum_3) < config.min_momentum_pct:
        direction = "flat"

    confidence = 0.42
    confidence += min(abs(momentum_3) / 0.4, 0.22)
    confidence += min(abs(momentum_7) / 0.9, 0.18)
    confidence += min(abs(short_latest - long_latest) / max(latest, 1e-9) * 120, 0.13)
    if tick_delta * momentum_3 > 0:
        confidence += 0.06
    if volatility > config.max_volatility_pct:
        confidence -= 0.2
    if gross_edge <= 0:
        confidence -= 0.12
    confidence = _clip_confidence(confidence)

    blockers: list[str] = []
    if direction == "flat":
        blockers.append("weak_momentum")
    if volatility > config.max_volatility_pct:
        blockers.append("excess_volatility")
    if confidence < config.min_confidence:
        blockers.append("low_confidence")
    if gross_edge <= 0:
        blockers.append("cost_edge_too_small")

    action = _neutral_action(config.asset_kind) if blockers else _directional_action(config.asset_kind, direction)
    stop_loss_pct = round(max(0.08, min(0.65, volatility * 0.35 + 0.08)), 3)
    take_profit_pct = round(max(stop_loss_pct * 1.15, abs(momentum_3) * 0.85), 3)
    return {
        "ok": True,
        "symbol": config.symbol,
        "asset_kind": config.asset_kind,
        "action": action,
        "confidence": confidence,
        "latest_price": latest,
        "momentum_3_pct": round(momentum_3, 4),
        "momentum_7_pct": round(momentum_7, 4),
        "tick_delta_pct": round(tick_delta, 4),
        "volatility_pct": round(volatility, 4),
        "short_ema": round(short_latest, 6),
        "long_ema": round(long_latest, 6),
        "gross_edge_pct": round(gross_edge, 4),
        "blockers": blockers,
        "risk": {
            "max_trade_amount": config.max_trade_amount,
            "cooldown_seconds": config.cooldown_seconds,
            "max_daily_loss_pct": config.max_daily_loss_pct,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
        },
        "rationale": (
            f"direction={direction}; momentum_3={momentum_3:.3f}%; "
            f"momentum_7={momentum_7:.3f}%; volatility={volatility:.3f}%; "
            f"confidence={confidence:.0%}"
        ),
    }


def micro_trade_config_from_goal(
    goal: str,
    symbol: str,
    *,
    asset_kind: AssetKind = "deriv",
    default_amount: float = 1.0,
) -> MicroTradeConfig:
    text = goal.lower()
    cadence = 15 if any(word in text for word in ["频繁", "高频", "scalp", "fast"]) else 60
    min_confidence = 0.64 if any(word in text for word in ["稳", "保守", "conservative"]) else 0.58
    max_volatility = 2.2 if asset_kind == "fund" else 2.8
    return MicroTradeConfig(
        symbol=symbol,
        asset_kind=asset_kind,
        cadence_seconds=cadence,
        max_trade_amount=max(0.35, float(default_amount)),
        min_confidence=min_confidence,
        max_volatility_pct=max_volatility,
    )
