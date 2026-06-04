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


def check_langgraph_compile() -> None:
    assert_true(web_app.advisor_langgraph_available(), "LangGraph is not available")
    graph = web_app.build_advisor_langgraph()
    assert_true(type(graph).__name__ == "CompiledStateGraph", "advisor graph did not compile")
    print("langgraph_compile: OK")


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
    check_langgraph_compile()
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
