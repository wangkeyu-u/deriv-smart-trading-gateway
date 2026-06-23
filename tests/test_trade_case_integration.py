from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

import web_app
from micro_trading import MicroTradeConfig
from trade_cases import control_trade_case, get_trade_case


def configure_runtime(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_app, "DB_PATH", tmp_path / "gateway.sqlite3")
    monkeypatch.setattr(web_app, "in_streamlit_runtime", lambda: True)
    st.session_state.clear()
    web_app.init_state()


def test_modules_advance_one_persistent_trade_case(monkeypatch, tmp_path) -> None:
    configure_runtime(monkeypatch, tmp_path)

    web_app.save_advisor_run(
        {
            "question": "Validate R_75 before a demo trade",
            "symbol": "R_75",
            "consensus": "CALL with confirmation",
            "stance": "CALL",
            "confidence": 0.72,
            "elapsed_ms": 120,
        }
    )
    case_id = st.session_state.active_trade_case_id
    advisor_case = get_trade_case(web_app.DB_PATH, case_id)
    assert advisor_case is not None
    assert advisor_case["stage"] == "advisor_review"

    web_app.add_chart_snapshot(
        {
            "ok": True,
            "data": {
                "symbol": "R_75",
                "granularity": 60,
                "returned_count": 2,
                "ohlcv": [],
            },
        },
        source="chart_agent",
    )
    chart_case = get_trade_case(web_app.DB_PATH, case_id)
    assert chart_case is not None
    assert chart_case["stage"] == "market_validation"

    web_app.save_micro_strategy_run(
        goal="Validate with a one-dollar paper strategy",
        config=MicroTradeConfig(symbol="R_75", max_trade_amount=1.0),
        decision={"action": "CALL", "confidence": 0.7},
        budget_check={"ok": True, "reason": "within_budget"},
        backtest={"summary": {"trade_count": 4, "total_pnl": 0.01, "halted": False}},
        operator_brief={"recommendation": "observe"},
        data_source="live",
    )
    micro_case = get_trade_case(web_app.DB_PATH, case_id)
    assert micro_case is not None
    assert micro_case["stage"] == "micro_backtest"

    web_app.set_pending_trade_state(
        {
            "action": "execute_simulated_trade",
            "symbol": "R_75",
            "amount": 1.0,
            "contract_type": "CALL",
            "duration": 5,
            "duration_unit": "t",
            "allow_live": False,
        },
        source="execution_agent",
    )
    pending_case = get_trade_case(web_app.DB_PATH, case_id)
    assert pending_case is not None
    assert pending_case["stage"] == "awaiting_confirmation"

    web_app.record_trade_receipt_state(
        {
            "ok": True,
            "data": {
                "receipt": {
                    "contract_id": "123",
                    "symbol": "R_75",
                    "purchase_price": 1.0,
                }
            },
        },
        source="execution_agent",
    )
    completed = get_trade_case(web_app.DB_PATH, case_id)
    assert completed is not None
    assert completed["stage"] == "review"
    assert completed["status"] == "completed"
    assert set(completed["context"]["artifacts"]) == {
        "advisor",
        "chart",
        "micro_strategy",
        "pending_trade",
        "trade_receipt",
    }


def test_paused_trade_case_does_not_accept_agent_artifacts(monkeypatch, tmp_path) -> None:
    configure_runtime(monkeypatch, tmp_path)
    case = web_app.create_active_trade_case("Pause before analysis", "R_100")
    paused = control_trade_case(
        web_app.DB_PATH,
        case["id"],
        "pause",
        expected_version=case["version"],
    )

    result = web_app.sync_active_trade_case_artifact(
        "advisor",
        actor="advisor",
        message="should not be written",
        payload={"stance": "CALL"},
    )

    assert result is not None
    assert result["status"] == "paused"
    restored = get_trade_case(web_app.DB_PATH, case["id"])
    assert restored is not None
    assert restored["version"] == paused["version"]
    assert restored["context"]["artifacts"] == {}


def rising_candle_result(symbol: str = "R_75") -> dict:
    start = datetime.now(timezone.utc) - timedelta(minutes=119)
    candles = []
    for index in range(120):
        close = 100 + index * 0.08
        candles.append(
            {
                "timestamp": (start + timedelta(minutes=index)).isoformat(),
                "open": close - 0.03,
                "high": close + 0.05,
                "low": close - 0.05,
                "close": close,
                "volume": 10,
            }
        )
    return {
        "ok": True,
        "data": {
            "symbol": symbol,
            "granularity": 60,
            "returned_count": len(candles),
            "ohlcv": candles,
        },
    }


def test_one_click_workflow_stops_at_human_confirmation(monkeypatch, tmp_path) -> None:
    configure_runtime(monkeypatch, tmp_path)
    case = web_app.create_active_trade_case("Validate R_75 with all agents", "R_75")
    advisor_calls = 0

    def fake_advisor(*_args, **_kwargs):
        nonlocal advisor_calls
        advisor_calls += 1
        return {
            "ok": True,
            "question": case["objective"],
            "symbol": "R_75",
            "stance": "CALL",
            "confidence": 0.8,
            "entry_price": 109.52,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    monkeypatch.setattr(web_app, "run_advisor_council", fake_advisor)
    monkeypatch.setattr(web_app, "fetch_compare_candles", lambda *_args, **_kwargs: rising_candle_result())

    result = web_app.run_trade_case_simulation(case["id"], amount=1.0, use_web=False)

    assert result["ok"] is True
    assert result["ready_for_confirmation"] is True
    assert advisor_calls == 1
    assert st.session_state.pending_trade["symbol"] == "R_75"
    restored = get_trade_case(web_app.DB_PATH, case["id"])
    assert restored is not None
    assert restored["status"] == "active"
    assert restored["stage"] == "awaiting_confirmation"
    assert restored["context"]["artifacts"]["risk"]["payload"]["ok"] is True
    assert restored["context"]["artifacts"]["workflow_run"]["payload"]["status"] == "awaiting_confirmation"


def test_failed_workflow_retries_from_market_step(monkeypatch, tmp_path) -> None:
    configure_runtime(monkeypatch, tmp_path)
    case = web_app.create_active_trade_case("Recover R_75 market failure", "R_75")
    advisor_calls = 0
    market_calls = 0

    def fake_advisor(*_args, **_kwargs):
        nonlocal advisor_calls
        advisor_calls += 1
        return {
            "ok": True,
            "question": case["objective"],
            "symbol": "R_75",
            "stance": "CALL",
            "confidence": 0.8,
            "entry_price": 109.52,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def flaky_market(*_args, **_kwargs):
        nonlocal market_calls
        market_calls += 1
        if market_calls == 1:
            return {"ok": False, "error": {"message": "temporary feed outage"}}
        return rising_candle_result()

    monkeypatch.setattr(web_app, "run_advisor_council", fake_advisor)
    monkeypatch.setattr(web_app, "fetch_compare_candles", flaky_market)

    failed = web_app.run_trade_case_simulation(case["id"], amount=1.0)
    failed_case = get_trade_case(web_app.DB_PATH, case["id"])
    recovered = web_app.run_trade_case_simulation(case["id"], amount=1.0, retry_failed=True)

    assert failed["ok"] is False
    assert failed["failed_step"] == "market"
    assert failed_case is not None and failed_case["status"] == "failed"
    assert recovered["ok"] is True
    assert recovered["ready_for_confirmation"] is True
    assert advisor_calls == 1
    assert market_calls == 2


def test_one_click_workflow_does_not_replace_existing_pending_trade(monkeypatch, tmp_path) -> None:
    configure_runtime(monkeypatch, tmp_path)
    case = web_app.create_active_trade_case("Do not replace pending trade", "R_75")
    st.session_state.pending_trade = {"symbol": "R_100", "amount": 1.0}
    monkeypatch.setattr(
        web_app,
        "run_advisor_council",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("advisor must not run")),
    )

    result = web_app.run_trade_case_simulation(case["id"])

    assert result["ok"] is False
    assert result["reason"] == "pending_trade_exists"
    assert st.session_state.pending_trade["symbol"] == "R_100"


def test_trade_case_restores_after_restart_without_restoring_confirmation(monkeypatch, tmp_path) -> None:
    configure_runtime(monkeypatch, tmp_path)
    case = web_app.create_active_trade_case("Persist R_75 workflow", "R_75")
    monkeypatch.setattr(
        web_app,
        "run_advisor_council",
        lambda *_args, **_kwargs: {
            "ok": True,
            "question": case["objective"],
            "symbol": "R_75",
            "stance": "CALL",
            "confidence": 0.8,
            "entry_price": 109.52,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    monkeypatch.setattr(web_app, "fetch_compare_candles", lambda *_args, **_kwargs: rising_candle_result())
    completed = web_app.run_trade_case_simulation(case["id"], amount=1.0)
    assert completed["ready_for_confirmation"] is True

    st.session_state.clear()
    web_app.init_state()
    web_app.hydrate_persisted_session_state()

    restored = get_trade_case(web_app.DB_PATH, case["id"])
    assert restored is not None
    assert st.session_state.active_trade_case_id == case["id"]
    assert st.session_state.pending_trade is None
    brief = web_app.trade_case_operator_brief(restored, has_session_pending=False, lang="zh")
    assert brief["headline"] == "原确认草稿已失效，需要重新验证"
