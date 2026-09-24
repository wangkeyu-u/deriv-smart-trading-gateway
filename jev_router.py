"""Bounded Jev decisions for read-only analysis, never trade authorization."""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx


JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
MAX_ROUTE_SECONDS = 1.2


@dataclass(frozen=True)
class ThinkingRoute:
    mode: str
    source: str
    latency_ms: float = 0.0
    confidence: float | None = None
    fast_probability: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketAssessment:
    stance: str | None
    source: str
    latency_ms: float = 0.0
    confidence: float | None = None
    probabilities: dict[str, float] | None = None
    model: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _choice_answer(answer: Any, options: set[str]) -> tuple[str, dict[str, float], float]:
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise ValueError("invalid Jev answer type")
    choice = answer.get("choice")
    if choice not in options:
        raise ValueError("invalid Jev choice")
    raw_probabilities = answer.get("probabilities")
    if not isinstance(raw_probabilities, dict) or set(raw_probabilities) != options:
        raise ValueError("invalid Jev distribution")
    probabilities = {key: float(raw_probabilities[key]) for key in options}
    confidence = float(answer["confidence"])
    if not all(math.isfinite(value) and 0 <= value <= 1 for value in (*probabilities.values(), confidence)):
        raise ValueError("invalid Jev probability")
    if abs(sum(probabilities.values()) - 1) > 0.02 or probabilities[choice] < max(probabilities.values()):
        raise ValueError("inconsistent Jev distribution")
    return choice, probabilities, confidence


def assess_market(
    state: dict[str, Any],
    api_key: str,
    *,
    deadline_at: float,
    model: str = JEV_MODEL,
) -> MarketAssessment:
    """Ask Jev for an actual CALL/PUT/WAIT advisory opinion from fresh market context."""
    if not api_key:
        return MarketAssessment(None, "disabled")
    remaining = deadline_at - time.perf_counter()
    if remaining < 1.4:
        return MarketAssessment(None, "deadline")
    started = time.perf_counter()
    try:
        response = httpx.post(
            JEV_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "state": state,
                "questions": {
                    "market_stance": {
                        "type": "choice",
                        "instructions": (
                            "For this read-only short-term market advisory, which stance best fits the supplied "
                            "market evidence and user question? Choose WAIT for weak, missing, or conflicting "
                            "evidence. This is not permission to place an order."
                        ),
                        "criteria": {
                            "CALL": "Observed short-term market evidence supports a bullish advisory stance.",
                            "PUT": "Observed short-term market evidence supports a bearish advisory stance.",
                            "WAIT": "Insufficient, mixed, stale, or weak evidence; defer directional advice.",
                        },
                    }
                },
            },
            timeout=min(MAX_ROUTE_SECONDS, remaining - 0.2),
        )
        response.raise_for_status()
        body = response.json()
        stance, probabilities, confidence = _choice_answer(body["answers"]["market_stance"], {"CALL", "PUT", "WAIT"})
        return MarketAssessment(
            stance,
            "jev",
            round((time.perf_counter() - started) * 1000, 1),
            confidence,
            probabilities,
            str(body.get("model") or model),
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        return MarketAssessment(None, "jev_error", round((time.perf_counter() - started) * 1000, 1))


def route_thinking(
    state: dict[str, Any],
    api_key: str,
    *,
    deadline_at: float | None = None,
    model: str = JEV_MODEL,
) -> ThinkingRoute:
    """Let Jev select a local fast path only when its typed answer is decisive.

    Failures and uncertainty use the existing deeper path. A deadline can skip
    the extra network hop altogether when there is too little time left.
    """
    if not api_key:
        return ThinkingRoute("deep", "disabled")
    remaining = deadline_at - time.perf_counter() if deadline_at is not None else None
    if remaining is not None and remaining < 3.0:
        return ThinkingRoute("fast", "deadline")
    timeout = min(MAX_ROUTE_SECONDS, remaining - 2.0) if remaining is not None else MAX_ROUTE_SECONDS
    payload = {
        "model": model,
        "state": state,
        "questions": {
            "thinking_path": {
                "type": "choice",
                "instructions": (
                    "Which analysis path should handle this request now? Select fast only when "
                    "the available evidence and simple local rules are enough. Select deep "
                    "for ambiguity, conflicting evidence, or reasoning that needs a language model. "
                    "This does not authorize any trade."
                ),
                "criteria": {
                    "fast": "Use the existing local analysis and concise answer immediately.",
                    "deep": "Use the existing language-model analysis when time permits.",
                },
            }
        },
    }
    started = time.perf_counter()
    try:
        response = httpx.post(
            JEV_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        choice, probabilities, confidence = _choice_answer(response.json()["answers"]["thinking_path"], {"fast", "deep"})
        fast_probability = probabilities["fast"]
        mode = "fast" if choice == "fast" and fast_probability >= 0.8 and confidence >= 0.7 else "deep"
        return ThinkingRoute(mode, "jev", round((time.perf_counter() - started) * 1000, 1), confidence, fast_probability)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        return ThinkingRoute("deep", "jev_error", round((time.perf_counter() - started) * 1000, 1))
