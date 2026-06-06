from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

import advisor_evaluation


def test_advisor_entry_price_prefers_latest_close() -> None:
    assert advisor_evaluation.advisor_entry_price(
        {
            "latest_close": 101.5,
            "tick": {"quote": 99.0},
        }
    ) == 101.5


def test_advisor_outcome_scores_call_and_put() -> None:
    call = advisor_evaluation.evaluate_advisor_outcome("CALL", 100.0, 101.0, 0.7)
    put = advisor_evaluation.evaluate_advisor_outcome("PUT", 100.0, 99.0, 0.6)
    wrong = advisor_evaluation.evaluate_advisor_outcome("PUT", 100.0, 101.0, 0.6)

    assert call["outcome"] == "correct"
    assert call["paper_return_pct"] == 1.0
    assert put["outcome"] == "correct"
    assert put["paper_return_pct"] == 1.0
    assert wrong["outcome"] == "wrong"
    assert wrong["paper_return_pct"] == -1.0


def test_advisor_wait_outcome_uses_threshold() -> None:
    quiet = advisor_evaluation.evaluate_advisor_outcome("WAIT", 100.0, 100.01, 0.5, wait_threshold_pct=0.03)
    missed = advisor_evaluation.evaluate_advisor_outcome("WAIT", 100.0, 101.0, 0.5, wait_threshold_pct=0.03)

    assert quiet["outcome"] == "correct_wait"
    assert quiet["score"] == 1.0
    assert missed["outcome"] == "missed_move"
    assert missed["score"] == 0.5


def test_advisor_outcome_pending_without_prices() -> None:
    result = advisor_evaluation.evaluate_advisor_outcome("CALL", None, 100.0)

    assert result["status"] == "pending"
    assert result["outcome"] == "no_price"
    assert result["score"] is None


def test_advisor_evaluation_summary() -> None:
    rows = [
        advisor_evaluation.evaluate_advisor_outcome("CALL", 100, 101),
        advisor_evaluation.evaluate_advisor_outcome("PUT", 100, 101),
        advisor_evaluation.evaluate_advisor_outcome("WAIT", 100, 100.01),
    ]

    summary = advisor_evaluation.summarize_advisor_evaluations(rows)

    assert summary["evaluated_count"] == 3
    assert summary["directional_count"] == 2
    assert summary["direction_accuracy"] == 0.5
    assert summary["average_score"] == 0.667


def test_advisor_horizon_evaluation_scores_multiple_windows() -> None:
    result = advisor_evaluation.evaluate_advisor_horizons(
        "CALL",
        100.0,
        [101.0, 102.0, 103.0, 104.0, 105.0, 104.5, 104.0, 103.5, 103.0, 102.5],
        0.8,
    )

    assert result["status"] == "evaluated"
    assert result["evaluated_count"] == 3
    assert result["horizons"]["1m"]["paper_return_pct"] == 1.0
    assert result["horizons"]["5m"]["paper_return_pct"] == 5.0
    assert result["horizons"]["10m"]["paper_return_pct"] == 2.5
    assert result["best_horizon"] == "5m"
    assert result["best_paper_return_pct"] == 5.0


def test_advisor_horizon_evaluation_pending_when_history_missing() -> None:
    result = advisor_evaluation.evaluate_advisor_horizons("PUT", 100.0, [], 0.4)

    assert result["status"] == "pending"
    assert result["evaluated_count"] == 0
    assert result["horizons"]["1m"]["status"] == "pending"


def test_future_closes_after_created_at() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-06-05T10:00:00Z",
                    "2026-06-05T10:01:00Z",
                    "2026-06-05T10:02:00Z",
                    "2026-06-05T10:03:00Z",
                ],
                utc=True,
            ),
            "close": [100.0, 101.0, 102.0, 103.0],
        }
    )

    assert advisor_evaluation.future_closes_after_created_at(frame, "2026-06-05T10:01:00Z", 2) == [102.0, 103.0]


def test_advisor_performance_summary_groups_by_symbol_and_stance() -> None:
    rows = [
        {
            "symbol": "R_75",
            "stance": "CALL",
            "status": "evaluated",
            "outcome": "correct",
            "score": 1.0,
            "paper_return_pct": 0.4,
            "horizon_average_score": 0.8,
        },
        {
            "symbol": "R_75",
            "stance": "CALL",
            "status": "evaluated",
            "outcome": "wrong",
            "score": 0.0,
            "paper_return_pct": -0.2,
            "horizon_average_score": 0.4,
        },
        {
            "symbol": "R_100",
            "stance": "WAIT",
            "status": "evaluated",
            "outcome": "correct_wait",
            "score": 1.0,
            "paper_return_pct": 0.0,
        },
    ]

    summary = advisor_evaluation.summarize_advisor_performance(rows)
    r75_call = next(item for item in summary if item["symbol"] == "R_75" and item["stance"] == "CALL")
    r100_wait = next(item for item in summary if item["symbol"] == "R_100" and item["stance"] == "WAIT")

    assert r75_call["runs"] == 2
    assert r75_call["accuracy"] == 0.5
    assert r75_call["average_score"] == 0.5
    assert r75_call["average_paper_return_pct"] == 0.1
    assert r75_call["average_horizon_score"] == 0.6
    assert r100_wait["accuracy"] == 1.0


def test_advisor_horizon_readiness() -> None:
    readiness = advisor_evaluation.advisor_horizon_readiness(
        "2026-06-05T10:00:00Z",
        now=datetime(2026, 6, 5, 10, 6, 30, tzinfo=timezone.utc),
    )

    assert readiness["age_seconds"] == 390.0
    assert readiness["ready"] == ["1m", "5m"]
    assert readiness["pending"] == ["10m"]


def test_advisor_horizon_readiness_handles_bad_timestamp() -> None:
    readiness = advisor_evaluation.advisor_horizon_readiness("not-a-date")

    assert readiness["age_seconds"] is None
    assert readiness["ready"] == []
    assert readiness["pending"] == ["1m", "5m", "10m"]


def test_advisor_evaluation_ready_requires_due_horizon_and_entry_price() -> None:
    assert advisor_evaluation.advisor_evaluation_ready(
        "2026-06-05T10:00:00Z",
        100.0,
        now=datetime(2026, 6, 5, 10, 1, 0, tzinfo=timezone.utc),
    ) is True
    assert advisor_evaluation.advisor_evaluation_ready(
        "2026-06-05T10:00:30Z",
        100.0,
        now=datetime(2026, 6, 5, 10, 1, 0, tzinfo=timezone.utc),
    ) is False
    assert advisor_evaluation.advisor_evaluation_ready(
        "2026-06-05T10:00:00Z",
        None,
        now=datetime(2026, 6, 5, 10, 2, 0, tzinfo=timezone.utc),
    ) is False
