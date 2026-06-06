from __future__ import annotations

import web_app
from micro_trading import MicroTradeConfig


def test_micro_strategy_run_persistence(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_app, "DB_PATH", tmp_path / "gateway.sqlite3")

    config = MicroTradeConfig(symbol="R_75", max_trade_amount=1.0)
    web_app.save_micro_strategy_run(
        goal="small fast paper strategy",
        config=config,
        decision={"action": "CALL", "confidence": 0.72},
        budget_check={"ok": True, "reason": "within_budget"},
        backtest={"summary": {"trade_count": 3, "total_pnl": 0.012, "halted": False}, "trades": []},
    )

    rows = web_app.load_recent_micro_strategy_runs(limit=3)

    assert len(rows) == 1
    assert rows[0]["symbol"] == "R_75"
    assert rows[0]["action"] == "CALL"
    assert rows[0]["budget_ok"] == 1
    assert rows[0]["trade_count"] == 3
    assert rows[0]["total_pnl"] == 0.012
