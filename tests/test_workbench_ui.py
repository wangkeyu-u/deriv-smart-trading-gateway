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
    next(item for item in ui.selectbox if item.label == "交易品种").select("自定义").run()
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
