"""Hand-labelled scenario fixtures. Synthetic data, never trading performance data."""
from __future__ import annotations

import time
from typing import Any


def snapshot(symbol: str = "frxEURUSD", trend: str = "up", quality: str = "ready", now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    direction = 1 if trend == "up" else -1 if trend == "down" else 0
    rows = []
    for i in range(30):
        close = 100 + direction * i * 0.1
        rows.append({"timestamp": now - (30 - i) * 60, "open": close, "high": close + .1, "low": close - .1, "close": close, "volume": 0})
    tick = {"symbol": symbol, "quote": rows[-1]["close"], "epoch": now - 1}
    if quality == "stale_tick":
        tick["epoch"] = now - 40
    elif quality == "missing_epoch":
        tick.pop("epoch")
    elif quality == "stale_candles":
        for row in rows:
            row["timestamp"] -= 600
    elif quality == "gap":
        rows.pop(10)
    return {"symbol": symbol, "tick": tick, "candles": {"ok": True, "data": {"symbol": symbol, "ohlcv": rows}}, "trend": trend, "summary": "Fixture observations"}


def choice(selected: str, options: list[str], strength: float = .94) -> dict[str, Any]:
    return {"type": "choice", "choice": selected, "probabilities": {option: strength if option == selected else (1 - strength) / (len(options) - 1) for option in options}, "confidence": .88 if strength >= .8 else .4}


def response(stance: str = "UP", path: str = "finish", thesis: str | None = None, strength: float = .94) -> dict[str, Any]:
    answers = {"market_stance": choice(stance, ["UP", "DOWN", "FLAT", "UNKNOWN"]), "reasoning_path": choice(path, ["finish", "deep", "wait"], strength)}
    if thesis:
        answers["thesis_status"] = choice(thesis, ["supported", "contradicted", "unclear"])
    return {"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 600, "output_tokens": 0}}


CASES = [
    {"id": "forex_observe", "scene": "observe", "symbol": "frxEURUSD", "question": "Summarize the observed trend.", "reply": response(), "expect": ["UP", "finish"]},
    {"id": "forex_complex", "scene": "observe", "symbol": "frxEURUSD", "question": "Explain why this trend might reverse and which assumptions need checking.", "reply": response(path="deep"), "expect": ["UP", "deep"]},
    {"id": "synthetic_news_thesis", "scene": "review", "symbol": "R_100", "question": "Fed news means this synthetic index must rise; should I buy CALL?", "thesis": "UP", "reply": response("UNKNOWN", "wait", "contradicted"), "expect": ["UNKNOWN", "wait"]},
    {"id": "synthetic_observe", "scene": "observe", "symbol": "R_75", "question": "Show the observed trend without predicting the next tick.", "reply": response("UNKNOWN"), "expect": ["UNKNOWN", "finish"]},
    {"id": "contrary_thesis", "scene": "review", "symbol": "frxEURUSD", "question": "I think this window is falling and want PUT.", "thesis": "DOWN", "reply": response("UP", "finish", "contradicted"), "expect": ["UNKNOWN", "finish"]},
    {"id": "supported_thesis", "scene": "review", "symbol": "frxEURUSD", "question": "This window looks upward, consistent with a CALL observation; is that interpretation fair?", "thesis": "UP", "reply": response("UP", "finish", "supported"), "expect": ["UP", "finish"]},
    {"id": "stale_tick", "scene": "observe", "symbol": "frxEURUSD", "question": "Current direction?", "quality": "stale_tick", "reply": response(), "expect": ["UNKNOWN", "wait"]},
    {"id": "missing_timestamp", "scene": "observe", "symbol": "frxEURUSD", "question": "Current direction?", "quality": "missing_epoch", "reply": response(), "expect": ["UNKNOWN", "wait"]},
    {"id": "stale_candles", "scene": "observe", "symbol": "frxEURUSD", "question": "Which direction does the current window support?", "quality": "stale_candles", "reply": response("UNKNOWN", "wait"), "expect": ["UNKNOWN", "wait"]},
    {"id": "uncertain_path", "scene": "observe", "symbol": "frxEURUSD", "question": "Does this need more explanation?", "reply": response(strength=.55), "expect": ["UNKNOWN", "deep"]},
    {"id": "research_request", "scene": "research", "symbol": "frxEURUSD", "question": "Research the assumptions behind this trend.", "reply": response(), "expect": ["UP", "deep"]},
    {"id": "unknown_instrument", "scene": "observe", "symbol": "UNKNOWN", "question": "Can this price window support a direction?", "reply": response(), "expect": ["UNKNOWN", "finish"]},
]
