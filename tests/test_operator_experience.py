from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

import web_app


def test_micro_operator_brief_prioritizes_readable_recommendation() -> None:
    frame = pd.DataFrame({"close": [100, 100.1, 100.2]})
    brief = web_app.micro_operator_brief(
        {
            "action": "CALL",
            "confidence": 0.72,
            "latest_price": 100.2,
            "momentum_3_pct": 0.2,
            "momentum_7_pct": 0.4,
            "volatility_pct": 0.12,
            "gross_edge_pct": 0.1,
            "risk": {"max_trade_amount": 1.0},
            "blockers": [],
        },
        {"ok": True, "reason": "within_budget"},
        {"summary": {"trade_count": 4, "total_pnl": 0.018, "ending_equity": 100.018, "halt_reason": None}},
        frame,
    )

    assert brief["recommendation"] == "PAPER_ONLY"
    assert brief["action"] == "CALL"
    assert brief["trade_count"] == 4
    assert "headline" in brief
    assert brief["next_steps"]


def test_micro_operator_brief_blocks_when_budget_fails() -> None:
    brief = web_app.micro_operator_brief(
        {"action": "CALL", "confidence": 0.9, "risk": {"max_trade_amount": 5}},
        {"ok": False, "reason": "single_trade_limit_exceeded"},
        {"summary": {}},
        pd.DataFrame({"close": [100]}),
    )

    assert brief["recommendation"] == "DO_NOT_TRADE"
    assert "single_trade_limit_exceeded" in " ".join(brief["risk_items"])


def test_micro_tables_keep_operator_relevant_columns() -> None:
    table = web_app.micro_trades_table(
        [
            {
                "index": 8,
                "action": "CALL",
                "entry_price": 100.0,
                "exit_price": 101.0,
                "amount": 1.0,
                "return_pct": 1.0,
                "pnl": 0.01,
                "equity": 100.01,
                "confidence": 0.72,
                "blockers": [],
                "raw_noise": "hidden",
            }
        ]
    )

    assert list(table.columns) == [
        "bar",
        "action",
        "entry",
        "exit",
        "amount",
        "return_%",
        "pnl",
        "equity",
        "confidence",
        "blockers",
    ]


def test_chart_data_status_uses_local_and_stale_status() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2026-06-06T15:08:00Z")],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
        }
    )

    status = web_app.chart_data_status(
        frame,
        60,
        now=datetime(2026, 6, 6, 15, 9, tzinfo=timezone.utc),
    )
    stale = web_app.chart_data_status(
        frame,
        60,
        now=datetime(2026, 6, 6, 15, 20, tzinfo=timezone.utc),
    )

    assert status["fresh"] is True
    assert status["latest_local"].endswith("MYT")
    assert "23:08:00" in status["latest_local"]
    assert stale["fresh"] is False


def test_local_time_label_converts_utc_to_myt() -> None:
    assert web_app.local_time_label("2026-06-06T15:08:00Z") == "2026-06-06 23:08:00 MYT"


def test_append_runtime_event_to_state_increments_sync_version() -> None:
    state = {"runtime_events": [], "sync_version": 7}

    web_app.append_runtime_event_to_state(
        state,
        {"time": "10:00:00.000", "kind": "chart", "source": "A", "target": "B", "message": "synced"},
    )

    assert state["sync_version"] == 8
    assert state["runtime_events"][-1]["kind"] == "chart"
