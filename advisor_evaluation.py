from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd


def advisor_entry_price(market: dict[str, Any]) -> float | None:
    for value in [
        market.get("latest_close"),
        (market.get("tick") or {}).get("quote") if isinstance(market.get("tick"), dict) else None,
    ]:
        if value is None:
            continue
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(price) and price > 0:
            return price
    return None


def evaluate_advisor_outcome(
    stance: str,
    entry_price: float | None,
    exit_price: float | None,
    confidence: float = 0.0,
    *,
    wait_threshold_pct: float = 0.03,
) -> dict[str, Any]:
    normalized_stance = str(stance or "WAIT").upper()
    if normalized_stance not in {"CALL", "PUT", "WAIT"}:
        normalized_stance = "WAIT"
    try:
        entry = float(entry_price) if entry_price is not None else None
        exit_value = float(exit_price) if exit_price is not None else None
    except (TypeError, ValueError):
        entry = None
        exit_value = None
    if not entry or not exit_value or not math.isfinite(entry) or not math.isfinite(exit_value):
        return {
            "status": "pending",
            "stance": normalized_stance,
            "entry_price": entry,
            "exit_price": exit_value,
            "price_delta": None,
            "return_pct": None,
            "paper_return_pct": None,
            "outcome": "no_price",
            "score": None,
            "confidence": round(float(confidence or 0), 3),
        }

    price_delta = exit_value - entry
    return_pct = price_delta / entry * 100
    if normalized_stance == "CALL":
        paper_return_pct = return_pct
        outcome = "correct" if paper_return_pct > 0 else "wrong" if paper_return_pct < 0 else "flat"
        score = 1.0 if paper_return_pct > 0 else 0.0 if paper_return_pct < 0 else 0.5
    elif normalized_stance == "PUT":
        paper_return_pct = -return_pct
        outcome = "correct" if paper_return_pct > 0 else "wrong" if paper_return_pct < 0 else "flat"
        score = 1.0 if paper_return_pct > 0 else 0.0 if paper_return_pct < 0 else 0.5
    else:
        paper_return_pct = 0.0
        if abs(return_pct) <= wait_threshold_pct:
            outcome = "correct_wait"
            score = 1.0
        else:
            outcome = "missed_move"
            score = 0.5

    return {
        "status": "evaluated",
        "stance": normalized_stance,
        "entry_price": round(entry, 8),
        "exit_price": round(exit_value, 8),
        "price_delta": round(price_delta, 8),
        "return_pct": round(return_pct, 5),
        "paper_return_pct": round(paper_return_pct, 5),
        "outcome": outcome,
        "score": score,
        "confidence": round(float(confidence or 0), 3),
    }


def summarize_advisor_evaluations(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [item for item in evaluations if item.get("status") == "evaluated"]
    directional = [item for item in evaluated if item.get("stance") in {"CALL", "PUT"}]
    correct_directional = [item for item in directional if item.get("outcome") == "correct"]
    scores = [float(item["score"]) for item in evaluated if item.get("score") is not None]
    returns = [
        float(item["paper_return_pct"])
        for item in directional
        if item.get("paper_return_pct") is not None
    ]
    return {
        "evaluated_count": len(evaluated),
        "directional_count": len(directional),
        "direction_accuracy": (
            round(len(correct_directional) / len(directional), 3)
            if directional
            else None
        ),
        "average_score": round(sum(scores) / len(scores), 3) if scores else None,
        "average_paper_return_pct": round(sum(returns) / len(returns), 5) if returns else None,
    }


def evaluate_advisor_horizons(
    stance: str,
    entry_price: float | None,
    future_closes: list[float],
    confidence: float = 0.0,
    horizons: tuple[int, ...] = (1, 5, 10),
) -> dict[str, Any]:
    horizon_results: dict[str, dict[str, Any]] = {}
    for horizon in horizons:
        close_index = horizon - 1
        exit_price = future_closes[close_index] if 0 <= close_index < len(future_closes) else None
        horizon_results[f"{horizon}m"] = evaluate_advisor_outcome(
            stance,
            entry_price,
            exit_price,
            confidence,
        )

    evaluated = [item for item in horizon_results.values() if item.get("status") == "evaluated"]
    directional = [item for item in evaluated if item.get("stance") in {"CALL", "PUT"}]
    best_label = None
    best_return = None
    if directional:
        best_label, best_result = max(
            (
                (label, result)
                for label, result in horizon_results.items()
                if result.get("status") == "evaluated" and result.get("stance") in {"CALL", "PUT"}
            ),
            key=lambda item: float(item[1].get("paper_return_pct") or 0),
        )
        best_return = best_result.get("paper_return_pct")
    return {
        "status": "evaluated" if evaluated else "pending",
        "horizons": horizon_results,
        "evaluated_count": len(evaluated),
        "best_horizon": best_label,
        "best_paper_return_pct": best_return,
        "average_score": (
            round(sum(float(item["score"]) for item in evaluated if item.get("score") is not None) / len(evaluated), 3)
            if evaluated
            else None
        ),
    }


def future_closes_after_created_at(frame: pd.DataFrame, created_at: str, limit: int = 10) -> list[float]:
    if frame.empty or not created_at:
        return []
    try:
        created_ts = pd.to_datetime(created_at, utc=True)
    except (TypeError, ValueError):
        return []
    future = frame[frame["timestamp"] > created_ts].head(limit)
    return [float(value) for value in future["close"].dropna().tolist()]


def summarize_advisor_performance(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row.get("symbol") or "UNKNOWN"), str(row.get("stance") or "WAIT"))
        groups.setdefault(key, []).append(row)

    summaries: list[dict[str, Any]] = []
    for (symbol, stance), items in sorted(groups.items()):
        evaluated = [item for item in items if item.get("status") == "evaluated"]
        correct = [
            item
            for item in evaluated
            if item.get("outcome") in {"correct", "correct_wait"}
        ]
        directional_returns = [
            float(item["paper_return_pct"])
            for item in evaluated
            if stance in {"CALL", "PUT"} and item.get("paper_return_pct") is not None
        ]
        scores = [
            float(item["score"])
            for item in evaluated
            if item.get("score") is not None
        ]
        horizon_scores = [
            float(item["horizon_average_score"])
            for item in items
            if item.get("horizon_average_score") is not None
        ]
        summaries.append(
            {
                "symbol": symbol,
                "stance": stance,
                "runs": len(items),
                "evaluated": len(evaluated),
                "accuracy": round(len(correct) / len(evaluated), 3) if evaluated else None,
                "average_score": round(sum(scores) / len(scores), 3) if scores else None,
                "average_paper_return_pct": (
                    round(sum(directional_returns) / len(directional_returns), 5)
                    if directional_returns
                    else None
                ),
                "average_horizon_score": (
                    round(sum(horizon_scores) / len(horizon_scores), 3)
                    if horizon_scores
                    else None
                ),
            }
        )
    return summaries


def advisor_horizon_readiness(
    created_at: str,
    *,
    now: datetime | None = None,
    horizons_minutes: tuple[int, ...] = (1, 5, 10),
) -> dict[str, Any]:
    if not created_at:
        return {"age_seconds": None, "ready": [], "pending": [f"{item}m" for item in horizons_minutes]}
    try:
        created = pd.to_datetime(created_at, utc=True).to_pydatetime()
    except (TypeError, ValueError):
        return {"age_seconds": None, "ready": [], "pending": [f"{item}m" for item in horizons_minutes]}
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age_seconds = max(0.0, (current - created).total_seconds())
    ready: list[str] = []
    pending: list[str] = []
    for minutes in horizons_minutes:
        label = f"{minutes}m"
        if age_seconds >= minutes * 60:
            ready.append(label)
        else:
            pending.append(label)
    return {
        "age_seconds": round(age_seconds, 1),
        "ready": ready,
        "pending": pending,
    }


def advisor_evaluation_ready(
    created_at: str,
    entry_price: float | None,
    *,
    now: datetime | None = None,
) -> bool:
    try:
        price = float(entry_price) if entry_price is not None else None
    except (TypeError, ValueError):
        return False
    if not price or not math.isfinite(price) or price <= 0:
        return False
    readiness = advisor_horizon_readiness(created_at, now=now)
    return bool(readiness.get("ready"))
