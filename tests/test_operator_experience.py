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
        data_source="live",
        symbol="R_75",
    )

    assert brief["recommendation"] == "观察跟踪"
    assert brief["action"] == "CALL"
    assert brief["action_label"] == "看涨 (CALL)"
    assert brief["data_quality"] == "实时K线"
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

    assert brief["recommendation"] == "禁止交易"
    assert "单笔金额超过限制" in " ".join(brief["risk_items"])


def test_micro_operator_brief_overrides_signal_when_backtest_is_weak() -> None:
    brief = web_app.micro_operator_brief(
        {"action": "CALL", "confidence": 0.94, "risk": {"max_trade_amount": 1}},
        {"ok": True, "reason": "within_budget"},
        {
            "summary": {
                "trade_count": 13,
                "win_rate": 0.4615,
                "total_pnl": -0.0008892,
                "halt_reason": "max_consecutive_losses",
            }
        },
        pd.DataFrame({"close": [100, 101]}),
        data_source="live",
        symbol="R_75",
    )

    assert brief["recommendation"] == "暂不执行"
    assert "纸面回测不支持执行" in brief["headline"]
    assert "连续亏损熔断" in brief["headline"]
    assert "max_consecutive_losses" not in brief["headline"]
    assert "预算状态：未超预算" in brief["risk_items"]


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

    assert list(table.columns) == ["K线序号", "方向", "入场价", "出场价", "收益率%", "盈亏", "权益", "置信度", "结果"]
    assert table.iloc[0]["方向"] == "看涨 (CALL)"
    assert table.iloc[0]["结果"] == "通过"


def test_micro_recent_runs_table_uses_operator_language() -> None:
    table = web_app.micro_recent_runs_table(
        [
            {
                "created_at": "2026-06-06T15:32:00+00:00",
                "symbol": "R_75",
                "action": "CALL",
                "total_pnl": -0.1,
                "payload": {
                    "data_source": "live",
                    "operator_brief": {
                        "recommendation": "暂不执行",
                        "action": "CALL",
                        "headline": "实时方向偏 CALL，但纸面回测不支持执行。",
                    },
                    "backtest": {
                        "summary": {
                            "win_rate": 0.36,
                            "total_pnl": -0.00299,
                            "halt_reason": "max_consecutive_losses",
                        }
                    },
                },
            }
        ]
    )

    assert list(table.columns) == ["时间", "资产", "数据", "建议", "方向", "胜率", "盈亏", "熔断", "结论"]
    assert table.iloc[0]["数据"] == "实时K线"
    assert table.iloc[0]["建议"] == "暂不执行"
    assert table.iloc[0]["熔断"] == "连续亏损熔断"
    assert "纸面回测不支持执行" in table.iloc[0]["结论"]


def test_micro_reason_labels_are_human_readable() -> None:
    assert web_app.micro_budget_reason_label("within_budget") == "未超预算"
    assert web_app.micro_halt_reason_label("max_consecutive_losses") == "连续亏损熔断"
    assert web_app.micro_blocker_label("weak_momentum") == "动量太弱"
    assert web_app.micro_action_label("WAIT") == "等待"


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


def test_chart_loader_accepts_multiple_deriv_markets() -> None:
    assert web_app.selected_chart_symbol("R_75", "") == "R_75"
    assert web_app.selected_chart_symbol("R_100", "boom1000") == "BOOM1000"
    assert web_app.selected_chart_symbol("R_100", "frxeurusd") == "frxEURUSD"


def test_candle_result_count_requires_drawable_data() -> None:
    assert web_app.candle_result_count({"ok": True, "data": {"returned_count": 0, "ohlcv": []}}) == 0
    assert web_app.candle_result_count({"ok": True, "data": {"ohlcv": [{"close": 1.0}]}}) == 1


def test_append_runtime_event_to_state_increments_sync_version() -> None:
    state = {"runtime_events": [], "sync_version": 7}

    web_app.append_runtime_event_to_state(
        state,
        {"time": "10:00:00.000", "kind": "chart", "source": "A", "target": "B", "message": "synced"},
    )

    assert state["sync_version"] == 8
    assert state["runtime_events"][-1]["kind"] == "chart"
