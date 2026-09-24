"""Bounded Jev routing for optional fast paths, never for trade authorization."""

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
        answer = response.json()["answers"]["thinking_path"]
        if answer.get("type") != "choice" or answer.get("choice") not in {"fast", "deep"}:
            raise ValueError("invalid Jev choice")
        probabilities = answer["probabilities"]
        fast_probability = float(probabilities["fast"])
        deep_probability = float(probabilities["deep"])
        confidence = float(answer["confidence"])
        if not all(math.isfinite(value) and 0 <= value <= 1 for value in (fast_probability, deep_probability, confidence)):
            raise ValueError("invalid Jev probability")
        if abs(fast_probability + deep_probability - 1) > 0.02:
            raise ValueError("invalid Jev distribution")
        mode = "fast" if answer["choice"] == "fast" and fast_probability >= 0.8 and confidence >= 0.7 else "deep"
        return ThinkingRoute(mode, "jev", round((time.perf_counter() - started) * 1000, 1), confidence, fast_probability)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        return ThinkingRoute("deep", "jev_error", round((time.perf_counter() - started) * 1000, 1))
