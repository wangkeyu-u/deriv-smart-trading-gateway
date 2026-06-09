"""Smoke tests for the Deriv Smart Trading Gateway.

Run:
    .venv/bin/python smoke_test.py
"""

from __future__ import annotations

import asyncio
import importlib
import json
from typing import Any

import web_app
from budget_guard import BudgetLimits, budget_guard_check
from micro_trading import MicroTradeConfig, analyze_micro_trade
from paper_trading import CircuitBreakerConfig, backtest_micro_strategy
from server import get_historical_candles, get_market_ticks


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_dependencies() -> None:
    for module_name in [
        "streamlit",
        "pandas",
        "plotly",
        "httpx",
        "websockets",
        "langgraph",
        "openai",
        "anthropic",
    ]:
        importlib.import_module(module_name)
    print("dependencies: OK")


def check_prompts_and_symbols() -> None:
    prompts = web_app.load_agent_prompts()
    assert_true("advisor.chief" in prompts, "missing advisor.chief prompt")
    assert_true(len(web_app.advisor_specs()) >= 5, "expected at least five advisor specs")
    cases = {
        "R_75": "R_75",
        "boom1000": "BOOM1000",
        "crash500": "CRASH500",
        "1hz100v": "1HZ100V",
        "frxeurusd": "frxEURUSD",
        "stpRNG": "stpRNG",
    }
    for raw, expected in cases.items():
        assert_true(web_app.extract_symbol(f"check {raw}") == expected, f"symbol parse failed: {raw}")
    print("prompts_and_symbols: OK")


def check_advisor_evaluation_logic() -> None:
    outcome = web_app.evaluate_advisor_outcome("CALL", 100.0, 101.0, 0.7)
    assert_true(outcome["status"] == "evaluated", "advisor evaluation did not complete")
    assert_true(outcome["outcome"] == "correct", "CALL outcome should be correct")
    summary = web_app.summarize_advisor_evaluations([outcome])
    assert_true(summary["direction_accuracy"] == 1.0, "direction accuracy should be 100%")
    horizons = web_app.evaluate_advisor_horizons("CALL", 100.0, [101.0, 102.0, 103.0, 104.0, 105.0])
    assert_true(horizons["status"] == "evaluated", "advisor horizon evaluation did not complete")
    assert_true(horizons["horizons"]["5m"]["paper_return_pct"] == 5.0, "5m horizon score mismatch")
    print("advisor_evaluation: OK")


def check_langgraph_compile() -> None:
    assert_true(web_app.advisor_langgraph_available(), "LangGraph is not available")
    graph = web_app.build_advisor_langgraph()
    assert_true(type(graph).__name__ == "CompiledStateGraph", "advisor graph did not compile")
    print("langgraph_compile: OK")


def check_micro_trading_engine() -> None:
    result = analyze_micro_trade(
        [{"close": value} for value in [100, 100.03, 100.06, 100.1, 100.15, 100.22, 100.3, 100.39]],
        MicroTradeConfig(symbol="R_75", min_confidence=0.5, max_volatility_pct=5.0),
    )
    assert_true(result.get("ok") is True, "micro trading engine failed")
    assert_true(result.get("action") in {"CALL", "PUT", "WAIT"}, "invalid micro trading action")
    print("micro_trading_engine: OK")


def check_budget_guard() -> None:
    allowed = budget_guard_check(
        action="execute_simulated_trade",
        amount=1,
        limits=BudgetLimits(max_single_trade_amount=1, max_daily_trade_budget=5, max_total_trade_budget=5),
    )
    blocked = budget_guard_check(
        action="execute_simulated_trade",
        amount=2,
        limits=BudgetLimits(max_single_trade_amount=1, max_daily_trade_budget=5, max_total_trade_budget=5),
    )
    assert_true(allowed["ok"] is True, "budget guard should allow one-dollar trade")
    assert_true(blocked["reason"] == "single_trade_limit_exceeded", "budget guard should block oversize trade")
    print("budget_guard: OK")


def check_paper_trading() -> None:
    result = backtest_micro_strategy(
        [{"close": value} for value in [100, 100.03, 100.06, 100.1, 100.15, 100.22, 100.3, 100.39, 100.49]],
        MicroTradeConfig(symbol="R_75", min_confidence=0.5, max_volatility_pct=5.0),
        CircuitBreakerConfig(max_trade_count=3),
        lookback_bars=8,
    )
    assert_true(result.get("ok") is True, "paper trading backtest failed")
    assert_true("summary" in result, "paper trading summary missing")
    print("paper_trading: OK")


async def check_deriv_market_tools() -> None:
    tick = json.loads(await get_market_ticks("R_75", False))
    candles = json.loads(await get_historical_candles("R_75", 60, 5))
    assert_true(bool(tick.get("ok")), f"tick failed: {tick}")
    assert_true(bool(candles.get("ok")), f"candles failed: {candles}")
    assert_true(((tick.get("data") or {}).get("tick") or {}).get("symbol") == "R_75", "tick symbol mismatch")
    assert_true((candles.get("data") or {}).get("returned_count") == 5, "candle count mismatch")
    print("deriv_market_tools: OK")


def check_advisor_runtime() -> dict[str, Any]:
    result = web_app.run_advisor_council(
        "R_75 smoke test: wait, call, or put?",
        "R_75",
        6,
        False,
        None,
    )
    assert_true(result.get("ok") is True, "advisor result not ok")
    assert_true(result.get("runtime") == "langgraph", "advisor did not use LangGraph")
    assert_true(len(result.get("opinions") or []) >= 5, "missing advisor opinions")
    assert_true(all("prompt" in item for item in result.get("opinions") or []), "advisor prompt missing")
    assert_true(result.get("stance") in {"CALL", "PUT", "WAIT"}, "invalid stance")
    print("advisor_runtime: OK")
    return result


async def main() -> None:
    check_dependencies()
    check_prompts_and_symbols()
    check_advisor_evaluation_logic()
    check_langgraph_compile()
    check_micro_trading_engine()
    check_budget_guard()
    check_paper_trading()
    await check_deriv_market_tools()
    result = check_advisor_runtime()
    print(
        "summary:",
        {
            "runtime": result.get("runtime"),
            "symbol": result.get("symbol"),
            "stance": result.get("stance"),
            "confidence": result.get("confidence"),
            "elapsed_ms": result.get("elapsed_ms"),
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
