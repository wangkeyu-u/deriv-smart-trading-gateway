from __future__ import annotations

import web_app


def test_symbol_normalization_and_extraction() -> None:
    cases = {
        "R_75": "R_75",
        "r100": "R_100",
        "R100": "R_100",
        "boom1000": "BOOM1000",
        "crash500": "CRASH500",
        "1hz100v": "1HZ100V",
        "jd75": "JD75",
        "frxeurusd": "frxEURUSD",
        "stpRNG": "stpRNG",
    }
    for raw, expected in cases.items():
        assert web_app.extract_symbol(f"帮我看 {raw}") == expected


def test_trade_parameter_extraction() -> None:
    text = "用 10 美金买 R_75 看涨，持续 5 ticks"
    assert web_app.has_trade_intent(text)
    assert web_app.extract_symbol(text) == "R_75"
    assert web_app.extract_amount(text) == 10
    assert web_app.extract_contract_type(text) == "CALL"
    assert web_app.extract_duration(text) == 5
    assert web_app.extract_duration_unit(text) == "t"


def test_plain_buy_r100_becomes_trade_intent_with_missing_fields() -> None:
    text = "帮我买r100"

    plan = web_app.local_rule_plan(text)

    assert web_app.has_trade_intent(text)
    assert web_app.extract_symbol(text) == "R_100"
    assert plan.action == "chat"
    assert "金额" in plan.rationale
    assert "方向" in plan.rationale


def test_condition_extraction() -> None:
    assert web_app.extract_condition("价格高于 350 就下单") == {
        "metric": "latest_tick",
        "operator": ">",
        "value": 350.0,
    }
    assert web_app.evaluate_condition({"operator": ">", "value": 10}, 11)[0] is True
    assert web_app.evaluate_condition({"operator": "<", "value": 10}, 11)[0] is False
