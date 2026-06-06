from __future__ import annotations

import web_app


def test_advisor_chart_overlay_matches_symbol() -> None:
    overlay = web_app.advisor_chart_overlay(
        "R_75",
        {
            "symbol": "R_75",
            "stance": "CALL",
            "confidence": 0.73,
            "entry_price": 123.45,
        },
    )

    assert overlay is not None
    assert overlay["stance"] == "CALL"
    assert overlay["price"] == 123.45
    assert overlay["color"] == "#00b894"
    assert overlay["label"] == "CALL · 73%"


def test_advisor_chart_overlay_ignores_other_symbols() -> None:
    assert web_app.advisor_chart_overlay(
        "R_100",
        {"symbol": "R_75", "stance": "PUT", "entry_price": 123.45},
    ) is None


def test_advisor_chart_overlay_requires_valid_price() -> None:
    assert web_app.advisor_chart_overlay(
        "R_75",
        {"symbol": "R_75", "stance": "WAIT", "entry_price": None},
    ) is None
