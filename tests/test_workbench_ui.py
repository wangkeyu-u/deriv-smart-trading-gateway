"""Exercise real Streamlit state changes without network or user storage."""
from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

import web_app
from evals.scenarios import snapshot


def app():
    return AppTest.from_string("import web_app\nweb_app.main()", default_timeout=8).run()


@pytest.mark.parametrize("has_market", [True, False])
def test_submit_runs_graph_in_streamlit_and_returns_visible_result(monkeypatch, has_market):
    monkeypatch.setattr(web_app, "advisor_market_snapshot", lambda *a, **k: snapshot("R_100") if has_market else {"symbol": "R_100", "summary": "offline"})
    ui = app()
    ui.text_area[0].input("UI smoke: inspect current observations")
    ui.button[0].click().run()
    assert not ui.exception
    result = ui.session_state["last_advisor_result"]
    assert result["ok"] is True
    assert result["status"] == ("completed" if has_market else "incomplete")
    assert result["stance"] == "WAIT"
    assert any("result-surface" in item.value for item in ui.markdown)


def test_custom_symbol_and_review_controls_update_before_submit():
    ui = app()
    next(item for item in ui.selectbox if item.label == "交易品种").select("custom").run()
    assert any(item.label == "自定义品种" for item in ui.text_input)
    ui.get("button_group")[1].set_value("review").run()
    assert not ui.exception
    assert ui.radio[0].label == "你的预期方向"
    assert ui.radio[0].value == "CALL"


def test_trade_confirmation_remains_bound_to_visible_pending_order():
    ui = app()
    pending = {"action": "execute_simulated_trade", "symbol": "R_75", "amount": 10, "contract_type": "CALL", "duration": 5, "duration_unit": "t"}
    ui.session_state["pending_trade"] = pending
    ui.get("button_group")[0].set_value("trade").run()
    assert not ui.exception
    assert any("R_75" in item.value for item in ui.json)
    confirm = next(item for item in ui.checkbox if item.label == web_app.text_for("zh", "confirm_next_trade"))
    assert not confirm.value
    confirm.check().run()
    assert ui.session_state["confirm_next_trade"] is True
    assert ui.session_state["pending_trade"] == pending


def test_multiple_chart_snapshots_render_one_set_of_controls():
    from datetime import datetime, timezone
    ui = app()
    market = snapshot("R_100")
    for row in market["candles"]["data"]["ohlcv"]:
        row["timestamp"] = datetime.fromtimestamp(row["timestamp"], timezone.utc).isoformat()
    saved = {"symbol": "R_100", "granularity": 60, "created_at": "2026-09-29T12:00:00Z", "result": market["candles"]}
    ui.session_state["chart_snapshots"] = [saved, saved]
    ui.get("button_group")[0].set_value("market").run()
    assert not ui.exception
    assert len(ui.get("plotly_chart")) == 1
    assert len([item for item in ui.slider if item.label == web_app.text_for("zh", "chart_height")]) == 1


def test_language_switch_keeps_settings_and_renders_english():
    ui = app()
    next(item for item in ui.selectbox if item.label == "语言").select("en").run()
    assert not ui.exception
    assert any(item.label == "Your question" for item in ui.text_area)
    assert any(item.label == "Run analysis" for item in ui.button)


def test_draft_and_review_parameters_survive_workspace_navigation():
    ui = app()
    next(item for item in ui.selectbox if item.label == "交易品种").select("custom").run()
    next(item for item in ui.text_input if item.label == "自定义品种").input("frxGBPUSD").run()
    ui.get("button_group")[1].set_value("review").run()
    ui.text_area[0].input("均线转弱，复核下行观察").run()
    ui.radio[0].set_value("PUT").run()
    ui.slider[0].set_value(15).run()
    ui.get("button_group")[0].set_value("market").run()
    ui.get("button_group")[0].set_value("analysis").run()
    assert not ui.exception
    assert ui.text_area[0].value == "均线转弱，复核下行观察"
    assert ui.radio[0].value == "PUT"
    assert ui.slider[0].value == 15
    assert ui.get("button_group")[1].value == "review"
    assert next(item for item in ui.text_input if item.label == "自定义品种").value == "frxGBPUSD"


def test_submitted_question_remains_available_for_repeat_analysis(monkeypatch):
    calls = []
    def market(*args, **kwargs):
        calls.append(args[0])
        return snapshot("R_100")
    monkeypatch.setattr(web_app, "advisor_market_snapshot", market)
    ui = app()
    ui.text_area[0].input("复查当前窗口")
    ui.button[0].click().run()
    ui.run()
    assert ui.text_area[0].value == "复查当前窗口"
    ui.button[0].click().run()
    assert calls == ["R_100", "R_100"]
    assert not ui.exception


def test_persisted_history_can_be_inspected_and_reused_without_network(monkeypatch):
    result = {
        "question": "复核 GBPUSD 下行观察", "symbol": "frxGBPUSD", "scene": "review", "thesis": "PUT",
        "time_budget_seconds": 15, "requested_web": False, "stance": "WAIT", "status": "completed",
        "created_at": "2026-09-29T12:00:00Z", "elapsed_ms": 500, "consensus": "历史判断",
        "evidence": {"status": "ready", "trend": "down"}, "thinking_route": {"mode": "finish"},
        "jev_assessment": {"source": "jev", "model": "jev-1.13.0", "path_probabilities": {"finish": .9, "deep": .05, "wait": .05}, "path_confidence": .8},
    }
    web_app.save_advisor_run(result)
    def unexpected_network(*args, **kwargs):
        raise AssertionError("Opening history or reusing inputs must not fetch market data")
    monkeypatch.setattr(web_app, "advisor_market_snapshot", unexpected_network)
    ui = app()
    ui.get("button_group")[0].set_value("audit").run()
    assert not ui.exception
    assert len(ui.get("download_button")) == 1
    assert any("历史快照" in item.value for item in ui.caption)
    assert any("当时有效" in item.value for item in ui.markdown)
    next(item for item in ui.button if item.label == "复用问题与参数").click().run()
    assert not ui.exception
    assert ui.get("button_group")[0].value == "analysis"
    assert ui.text_area[0].value == result["question"]
    assert ui.radio[0].value == "PUT"
    assert ui.slider[0].value == 15
    assert next(item for item in ui.selectbox if item.label == "交易品种").value == "frxGBPUSD"


def test_unreadable_history_record_preserves_summary():
    import sqlite3
    web_app.save_advisor_run({"question": "legacy", "consensus": "原始摘要仍可用"})
    with sqlite3.connect(web_app.DB_PATH) as conn:
        conn.execute("UPDATE advisor_runs SET result_json = 'invalid json'")
    ui = app()
    ui.get("button_group")[0].set_value("audit").run()
    assert not ui.exception
    assert any("原始摘要仍可用" in item.value for item in ui.markdown)
