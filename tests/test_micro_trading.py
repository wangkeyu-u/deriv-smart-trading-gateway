from __future__ import annotations

import pandas as pd

from micro_trading import MicroTradeConfig, analyze_micro_trade, micro_trade_config_from_goal


def test_micro_trade_deriv_detects_upward_scalp_signal() -> None:
    frame = pd.DataFrame({"close": [100, 100.03, 100.06, 100.1, 100.15, 100.22, 100.3, 100.39, 100.49]})
    result = analyze_micro_trade(
        frame,
        MicroTradeConfig(symbol="R_75", asset_kind="deriv", min_confidence=0.5, max_volatility_pct=5.0),
    )

    assert result["ok"] is True
    assert result["action"] == "CALL"
    assert result["confidence"] >= 0.5
    assert result["blockers"] == []


def test_micro_trade_waits_when_momentum_is_weak() -> None:
    frame = pd.DataFrame({"close": [100.0, 100.01, 100.0, 100.01, 100.0, 100.01, 100.0, 100.01]})
    result = analyze_micro_trade(frame, MicroTradeConfig(symbol="R_75", asset_kind="deriv"))

    assert result["ok"] is True
    assert result["action"] == "WAIT"
    assert "weak_momentum" in result["blockers"]


def test_micro_trade_fund_uses_spot_actions() -> None:
    frame = pd.DataFrame({"close": [10, 10.02, 10.05, 10.09, 10.13, 10.18, 10.24, 10.31]})
    result = analyze_micro_trade(
        frame,
        MicroTradeConfig(symbol="FUND_X", asset_kind="fund", min_confidence=0.5, max_volatility_pct=5.0),
    )

    assert result["action"] in {"BUY", "HOLD"}
    assert result["action"] != "CALL"


def test_micro_trade_config_from_goal_tightens_fast_goal() -> None:
    config = micro_trade_config_from_goal("帮我高频小额交易，尽量保守", "R_75", default_amount=0.5)

    assert config.cadence_seconds == 15
    assert config.min_confidence == 0.64
    assert config.max_trade_amount == 0.5
