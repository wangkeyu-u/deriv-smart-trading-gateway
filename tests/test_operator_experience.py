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


def test_chart_integrity_report_accepts_regular_fresh_candles() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-06-06T15:00:00Z", periods=4, freq="1min"),
            "open": [100.0, 100.1, 100.2, 100.3],
            "high": [100.2, 100.3, 100.4, 100.5],
            "low": [99.9, 100.0, 100.1, 100.2],
            "close": [100.1, 100.2, 100.3, 100.4],
        }
    )

    report = web_app.chart_integrity_report(
        frame,
        60,
        now=datetime(2026, 6, 6, 15, 4, tzinfo=timezone.utc),
    )

    assert report["ok"] is True
    assert report["issues"] == []
    assert report["gap_count"] == 0


def test_chart_integrity_report_explains_corrupted_candles() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-06-06T15:00:00Z",
                    "2026-06-06T15:01:00Z",
                    "2026-06-06T15:01:00Z",
                    "2026-06-06T15:05:00Z",
                    "2026-06-06T15:04:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 100.1, 100.2, 100.3, 100.4],
            "high": [100.2, 100.3, 100.1, 100.5, 100.6],
            "low": [99.9, 100.0, 100.1, 100.2, 100.3],
            "close": [100.1, 100.2, 100.3, 100.4, 100.5],
        }
    )

    report = web_app.chart_integrity_report(
        frame,
        60,
        now=datetime(2026, 6, 6, 15, 5, tzinfo=timezone.utc),
    )

    assert report["ok"] is False
    assert report["duplicate_timestamps"] == 1
    assert report["out_of_order_bars"] == 1
    assert report["gap_count"] == 1
    assert report["invalid_ohlc"] == 1


def test_chart_integrity_report_handles_non_finite_prices() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2026-06-06T15:00:00Z")],
            "open": [float("inf")],
            "high": [2.0],
            "low": [1.0],
            "close": [1.5],
        }
    )

    report = web_app.chart_integrity_report(
        frame,
        60,
        now=datetime(2026, 6, 6, 15, 1, tzinfo=timezone.utc),
    )

    assert report["ok"] is False
    assert report["invalid_ohlc"] == 1
    assert "invalid_ohlc" in report["issues"]


def test_chart_snapshot_id_includes_subsecond_precision() -> None:
    first = web_app.chart_snapshot_id(
        "R_100",
        datetime(2026, 6, 6, 15, 8, 0, 1, tzinfo=timezone.utc),
    )
    second = web_app.chart_snapshot_id(
        "R_100",
        datetime(2026, 6, 6, 15, 8, 0, 2, tzinfo=timezone.utc),
    )

    assert first != second
    assert first.endswith("000001Z")


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


def test_case_blocker_messages_follow_interface_language() -> None:
    assert web_app.case_blocker_message("advisor_not_actionable", "zh") == "谋士团建议等待，当前不应生成订单"
    assert web_app.case_blocker_message("advisor_not_actionable", "en") == "Advisor stance is WAIT or invalid."


def test_display_case_blockers_cleans_legacy_wait_artifacts() -> None:
    blockers = web_app.display_case_blockers(
        ["advisor_not_actionable", "backtest_halted", "missing_trade_draft", "direction_conflict"],
        {"advisor_action": "WAIT", "micro_action": "PUT", "pending_action": None},
    )

    assert blockers == ["advisor_not_actionable", "backtest_halted"]


def test_operator_brief_explains_backtest_halt_in_plain_chinese() -> None:
    case = {
        "status": "active",
        "stage": "risk_review",
        "symbol": "R_75",
        "context": {
            "artifacts": {
                "advisor": {"payload": {"stance": "WAIT", "confidence": 0.62}},
                "micro_strategy": {
                    "payload": {
                        "decision": {"action": "PUT", "confidence": 0.95},
                        "budget_guard": {"ok": True},
                        "backtest": {
                            "summary": {
                                "trade_count": 3,
                                "wins": 0,
                                "losses": 3,
                                "win_rate": 0,
                                "total_pnl": -0.002,
                                "halted": True,
                                "halt_reason": "max_consecutive_losses",
                            }
                        },
                    }
                },
                "risk": {
                    "payload": {
                        "ok": False,
                        "blockers": ["advisor_not_actionable", "backtest_halted"],
                    }
                },
                "workflow_run": {
                    "payload": {"status": "blocked", "failed_step": "advisor"}
                },
            }
        },
    }

    brief = web_app.trade_case_operator_brief(case, lang="zh")

    assert brief["headline"] == "本轮不下单"
    assert "连续亏损 3 次" in brief["summary"]
    assert brief["next_action"] == "重新咨询谋士"
    assert brief["decision"] == "NO_TRADE"


def test_operator_brief_requires_revalidation_after_restart() -> None:
    case = {
        "status": "active",
        "stage": "awaiting_confirmation",
        "symbol": "R_75",
        "context": {
            "artifacts": {
                "workflow_run": {"payload": {"status": "awaiting_confirmation"}},
                "pending_trade": {"payload": {"contract_type": "CALL", "amount": 1.0}},
            }
        },
    }

    expired = web_app.trade_case_operator_brief(case, has_session_pending=False, lang="zh")
    ready = web_app.trade_case_operator_brief(case, has_session_pending=True, lang="zh")

    assert expired["headline"] == "原确认草稿已失效，需要重新验证"
    assert expired["decision"] == "NO_TRADE"
    assert ready["headline"] == "订单草稿已准备，等待你确认"
    assert ready["decision"] == "CALL"
