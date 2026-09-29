from __future__ import annotations

import time
from email.utils import formatdate

import pytest

import advisory_policy as policy
import jev_router
import web_app
from evals.scenarios import CASES, response, snapshot


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_scenario_policy_replay(monkeypatch, case):
    market = snapshot(case["symbol"], quality=case.get("quality", "ready"))
    state = policy.build_state(case["question"], case["symbol"], market, [], case["scene"], case.get("thesis", ""), 10)
    monkeypatch.setattr(jev_router, "_request", lambda *args: case["reply"])
    assessment = jev_router.assess_market(state, "key", deadline_at=time.perf_counter() + 3)
    decision = policy.decide(state, assessment, "CALL", enabled=True)
    assert [decision["stance"], decision["requested_path"]] == case["expect"]


@pytest.mark.parametrize("quote,epoch", [(True, 0), (float("nan"), 0), (100, None), (100, "123"), (100, float("inf"))])
def test_invalid_tick_fails_closed(quote, epoch):
    assert not policy.tick_is_current({"tick": {"quote": quote, "epoch": epoch}})


@pytest.mark.parametrize("quality,status", [("stale_candles", "stale_candles"), ("gap", "invalid_candles"), ("missing_epoch", "no_current_tick")])
def test_candle_integrity_and_freshness(quality, status):
    assert policy.market_evidence(snapshot(quality=quality), "frxEURUSD")["status"] == status


def test_malformed_and_wrong_symbol_candles_cannot_supply_trend():
    market = snapshot()
    market["candles"]["data"]["ohlcv"][4]["high"] = .01
    assert policy.market_evidence(market, "frxEURUSD")["status"] == "invalid_candles"
    market = snapshot()
    market["candles"]["data"]["symbol"] = "R_100"
    assert policy.market_evidence(market, "frxEURUSD")["status"] == "symbol_mismatch"


def test_news_date_filter_and_synthetic_exclusion():
    sources = [{"title": "fresh", "published": formatdate(time.time() - 60, usegmt=True)}, {"title": "old", "published": formatdate(time.time() - 90000, usegmt=True)}, {"title": "unknown"}]
    assert [s["title"] for s in policy.relevant_news(sources, "frxEURUSD")] == ["fresh"]
    assert policy.relevant_news(sources, "R_100") == []


def synthesize(monkeypatch, *, path="finish", scene="observe", thesis="", quality="ready", llm=True, budget=10, enabled=True, symbol="frxEURUSD", thesis_status=None):
    body = response("CALL", path, thesis_status)
    monkeypatch.setattr(jev_router, "_request", lambda *args: body)
    calls = []
    monkeypatch.setattr(web_app, "advisor_llm_synthesis", lambda *args: calls.append(args) or "explanation")
    market = snapshot(symbol, quality=quality)
    result = web_app.advisor_synthesis_with_jev("review this", symbol, market, [], [], {"stance": "CALL", "confidence": .6, "summary": "local", "vote_counts": {"CALL": 3, "WAIT": 2}}, time.perf_counter(), budget, jev_enabled=enabled, jev_api_key="key", llm_config={"provider": "OpenAI", "api_key": "key", "model": "example"} if llm else {}, scene=scene, thesis=thesis)
    return result, calls


def test_jev_actually_controls_explanation_invocation(monkeypatch):
    (summary, route, _, _, _), calls = synthesize(monkeypatch, path="finish")
    assert summary is None and not calls and route["mode"] == "finish"
    (summary, route, _, _, _), calls = synthesize(monkeypatch, path="deep")
    assert summary == "explanation" and len(calls) == 1 and route["mode"] == "deep"
    (summary, route, _, consensus, _), calls = synthesize(monkeypatch, path="wait")
    assert summary is None and not calls and route["mode"] == "wait" and consensus["stance"] == "WAIT"


@pytest.mark.parametrize("kwargs,status", [({"llm": False}, "not_configured"), ({"budget": 2}, "budget_exhausted")])
def test_unfulfilled_deep_request_is_visible_wait(monkeypatch, kwargs, status):
    (_, route, _, consensus, _), calls = synthesize(monkeypatch, path="deep", **kwargs)
    assert route["requested_path"] == "deep" and route["mode"] == "wait"
    assert route["explanation_status"] == status
    assert consensus["stance"] == "WAIT" and not calls


@pytest.mark.parametrize("enabled", [True, False])
def test_stale_data_blocks_model_with_or_without_jev(monkeypatch, enabled):
    (_, route, assessment, consensus, _), calls = synthesize(monkeypatch, quality="stale_tick", enabled=enabled)
    assert assessment["source"] == "no_current_tick"
    assert route["mode"] == "wait" and consensus["stance"] == "WAIT"
    assert not calls
    assert consensus["confidence"] == .6  # Never rewrite local rule vote share.


def test_synthetic_never_promoted_even_by_decisive_jev(monkeypatch):
    (_, _, _, consensus, _), _ = synthesize(monkeypatch, symbol="R_100")
    assert consensus["stance"] == "WAIT"


def test_model_error_cannot_preserve_directional_local_vote(monkeypatch):
    market = snapshot()
    state = policy.build_state("observe", "frxEURUSD", market, [], "observe", "", 10)
    decision = policy.decide(state, jev_router.MarketAssessment(None, "jev_error", error_code="timeout"), "CALL", enabled=True)
    assert decision["stance"] == "WAIT"
    assert decision["requested_path"] == "deep"


def test_thesis_cannot_be_invented():
    with pytest.raises(ValueError, match="explicit"):
        web_app.run_advisor_council("review", "R_100", 10, False, scene="review")


def test_incomplete_synthetic_window_does_not_trigger_explanation(monkeypatch):
    (_, route, _, consensus, _), calls = synthesize(monkeypatch, symbol="R_100", quality="stale_candles", path="deep")
    assert route["mode"] == "wait"
    assert route["reason"] == "stale_candles"
    assert consensus["stance"] == "WAIT"
    assert not calls
