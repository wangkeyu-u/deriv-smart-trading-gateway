from __future__ import annotations

import pandas as pd

from micro_trading import MicroTradeConfig
from paper_trading import (
    CircuitBreakerConfig,
    backtest_micro_strategy,
    evaluate_circuit_breaker,
    paper_trade_return_pct,
)


def test_paper_trade_return_handles_call_put_and_hold() -> None:
    assert paper_trade_return_pct("CALL", 100.0, 101.0) == 1.0
    assert paper_trade_return_pct("PUT", 100.0, 99.0) == 1.0
    assert paper_trade_return_pct("HOLD", 100.0, 99.0) == 0.0


def test_circuit_breaker_halts_on_consecutive_losses() -> None:
    result = evaluate_circuit_breaker(
        [
            {"pnl": -0.1, "equity": 99.9},
            {"pnl": -0.2, "equity": 99.7},
            {"pnl": -0.1, "equity": 99.6},
        ],
        CircuitBreakerConfig(max_consecutive_losses=3),
    )

    assert result["halted"] is True
    assert result["reason"] == "max_consecutive_losses"


def test_backtest_micro_strategy_produces_trade_summary() -> None:
    closes = [
        100.0,
        100.03,
        100.06,
        100.1,
        100.15,
        100.22,
        100.3,
        100.39,
        100.49,
        100.61,
        100.74,
        100.88,
        101.03,
        101.19,
        101.36,
        101.54,
    ]
    result = backtest_micro_strategy(
        pd.DataFrame({"close": closes}),
        MicroTradeConfig(symbol="R_75", min_confidence=0.5, max_volatility_pct=5.0),
        CircuitBreakerConfig(max_trade_count=4),
        lookback_bars=8,
    )

    assert result["ok"] is True
    assert result["summary"]["trade_count"] > 0
    assert "win_rate" in result["summary"]
    assert result["summary"]["halted"] in {True, False}
