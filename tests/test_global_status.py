from __future__ import annotations

from datetime import datetime, timezone

import web_app


def test_global_status_prefers_advisor_result() -> None:
    snapshot = web_app.global_status_snapshot(
        {
            "advisor_symbol": "R_100",
            "last_advisor_result": {
                "symbol": "R_75",
                "stance": "CALL",
                "confidence": 0.72,
                "entry_price": 123.45,
            },
            "api_trace": [{"tool": "get_market_ticks"}],
            "sync_version": 4,
            "pending_trade": None,
        }
    )

    assert snapshot["symbol"] == "R_75"
    assert snapshot["advisor_stance"] == "CALL"
    assert snapshot["advisor_confidence"] == 0.72
    assert snapshot["entry_price"] == 123.45
    assert snapshot["api_calls"] == 1
    assert snapshot["sync_version"] == 4
    assert snapshot["pending_trade"] is False


def test_global_status_falls_back_to_tick_and_pending_trade() -> None:
    snapshot = web_app.global_status_snapshot(
        {
            "advisor_symbol": "R_100",
            "last_tick": {"data": {"symbol": "BOOM1000"}},
            "last_advisor_result": None,
            "api_trace": [],
            "sync_version": 0,
            "pending_trade": {"action": "execute_simulated_trade"},
        }
    )

    assert snapshot["symbol"] == "BOOM1000"
    assert snapshot["advisor_stance"] == "WAIT"
    assert snapshot["pending_trade"] is True


def test_safety_gate_snapshot_requires_token_and_confirmation() -> None:
    snapshot = web_app.safety_gate_snapshot(
        {
            "deriv_token": "",
            "require_trade_confirmation": True,
            "confirm_next_trade": False,
            "allow_live_execution": False,
            "pending_trade": None,
        }
    )

    assert snapshot["has_token"] is False
    assert snapshot["confirmation_ready"] is False
    assert snapshot["live_enabled"] is False
    assert snapshot["write_ready"] is False


def test_safety_gate_snapshot_ready_without_pending_trade() -> None:
    snapshot = web_app.safety_gate_snapshot(
        {
            "deriv_token": "demo-token",
            "require_trade_confirmation": True,
            "confirm_next_trade": True,
            "allow_live_execution": False,
            "pending_trade": None,
        }
    )

    assert snapshot["has_token"] is True
    assert snapshot["confirmation_ready"] is True
    assert snapshot["pending_trade"] is False
    assert snapshot["write_ready"] is True


def test_timestamp_age_seconds_handles_iso_values() -> None:
    age = web_app.timestamp_age_seconds(
        "2026-06-05T10:00:00Z",
        now=datetime(2026, 6, 5, 10, 0, 12, tzinfo=timezone.utc),
    )

    assert age == 12.0
    assert web_app.timestamp_age_seconds("not-a-date") is None


def test_freshness_snapshot_tracks_fresh_stale_and_missing_sources() -> None:
    snapshot = web_app.freshness_snapshot(
        {
            "last_tick": {
                "timestamp": "2026-06-05T10:00:55Z",
                "data": {"tick": {"timestamp": "2026-06-05T10:00:56Z"}},
            },
            "chart_snapshots": [{"created_at": "2026-06-05T09:55:00Z"}],
            "last_advisor_result": {"created_at": "2026-06-05T10:00:00Z"},
        },
        now=datetime(2026, 6, 5, 10, 1, 0, tzinfo=timezone.utc),
    )

    assert snapshot["known_count"] == 3
    assert snapshot["fresh_count"] == 2
    assert snapshot["stale_count"] == 1
    assert snapshot["ok"] is False
    assert snapshot["items"]["tick"]["status"] == "fresh"
    assert snapshot["items"]["chart"]["status"] == "stale"
    assert snapshot["items"]["advisor"]["status"] == "fresh"


def test_safety_gate_snapshot_exposes_data_freshness_without_blocking_write_ready() -> None:
    snapshot = web_app.safety_gate_snapshot(
        {
            "deriv_token": "demo-token",
            "require_trade_confirmation": False,
            "confirm_next_trade": False,
            "allow_live_execution": False,
            "pending_trade": None,
            "last_tick": {"timestamp": "2026-06-05T10:00:00Z"},
            "chart_snapshots": [],
            "last_advisor_result": None,
        }
    )

    assert "data_freshness_ok" in snapshot
    assert snapshot["write_ready"] is True


def test_execution_audit_snapshot_excludes_token_and_includes_decision_context() -> None:
    snapshot = web_app.execution_audit_snapshot(
        {
            "deriv_token": "secret-token",
            "advisor_symbol": "R_75",
            "last_advisor_result": {
                "ok": True,
                "created_at": "2026-06-05T10:00:00Z",
                "symbol": "R_75",
                "stance": "CALL",
                "confidence": 0.71,
                "entry_price": 123.45,
                "runtime": "langgraph",
                "source_count": 2,
                "vote_counts": {"CALL": 2, "PUT": 0, "WAIT": 1},
                "consensus": "CALL with caution",
            },
            "pending_trade": {
                "action": "execute_simulated_trade",
                "symbol": "R_75",
                "amount": 1.0,
                "contract_type": "CALL",
                "duration": 5,
                "duration_unit": "t",
                "allow_live": False,
            },
            "api_trace": [{"tool": "get_market_ticks", "params": {"api_token": "***"}}],
            "runtime_events": [{"kind": "advisor"}],
            "chart_snapshots": [],
            "team_events": ["event"],
        }
    )

    assert snapshot["schema_version"] == 1
    assert snapshot["advisor"]["runtime"] == "langgraph"
    assert snapshot["pending_trade_summary"]["advisor_alignment"] == "aligned"
    assert "deriv_token" not in snapshot
    assert "secret-token" not in str(snapshot)


def test_system_health_snapshot_checks_local_runtime_without_requiring_token() -> None:
    snapshot = web_app.system_health_snapshot(
        {
            "deriv_token": "",
            "pending_trade": None,
            "last_tick": None,
            "last_advisor_result": None,
            "chart_snapshots": [],
            "api_trace": [{"tool": "get_market_ticks"}],
            "runtime_events": [{"kind": "api"}],
        }
    )

    assert snapshot["checks"]["db"]["ok"] is True
    assert snapshot["checks"]["langgraph"]["ok"] is True
    assert snapshot["checks"]["token"]["ok"] is False
    assert snapshot["ok"] is True
    assert snapshot["api_trace_count"] == 1
    assert snapshot["runtime_event_count"] == 1
