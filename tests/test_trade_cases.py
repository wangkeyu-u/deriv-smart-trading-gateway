from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from trade_cases import (
    TradeCaseConflict,
    TradeCaseTransitionError,
    control_trade_case,
    create_trade_case,
    get_trade_case,
    list_trade_case_events,
    list_trade_cases,
    record_trade_case_artifact,
)


def test_trade_case_persists_artifacts_and_progress(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    case = create_trade_case(db_path, objective="Validate R_75", symbol="R_75")

    case = record_trade_case_artifact(
        db_path,
        case["id"],
        artifact_type="advisor",
        actor="advisor_council",
        message="Advisor result saved",
        payload={"stance": "CALL", "confidence": 0.7},
        expected_version=case["version"],
    )
    case = record_trade_case_artifact(
        db_path,
        case["id"],
        artifact_type="micro_strategy",
        actor="micro_strategy",
        message="Backtest saved",
        payload={"trade_count": 7, "total_pnl": 0.01},
        expected_version=case["version"],
    )

    restored = get_trade_case(db_path, case["id"])
    assert restored is not None
    assert restored["stage"] == "micro_backtest"
    assert restored["version"] == 3
    assert restored["context"]["artifacts"]["advisor"]["payload"]["stance"] == "CALL"
    assert len(list_trade_case_events(db_path, case["id"])) == 3
    assert list_trade_cases(db_path)[0]["id"] == case["id"]


def test_trade_case_control_transitions_are_guarded(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    case = create_trade_case(db_path, objective="Pause safely", symbol="R_100")

    paused = control_trade_case(db_path, case["id"], "pause", expected_version=case["version"])
    resumed = control_trade_case(db_path, case["id"], "resume", expected_version=paused["version"])
    cancelled = control_trade_case(db_path, case["id"], "cancel", expected_version=resumed["version"])

    assert paused["status"] == "paused"
    assert resumed["status"] == "active"
    assert cancelled["status"] == "cancelled"
    with pytest.raises(TradeCaseTransitionError):
        control_trade_case(db_path, case["id"], "resume")


def test_trade_case_rejects_stale_version(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    case = create_trade_case(db_path, objective="Concurrent updates", symbol="R_50")
    record_trade_case_artifact(
        db_path,
        case["id"],
        artifact_type="advisor",
        actor="advisor",
        message="first update",
        payload={},
        expected_version=case["version"],
    )

    with pytest.raises(TradeCaseConflict):
        record_trade_case_artifact(
            db_path,
            case["id"],
            artifact_type="chart",
            actor="chart",
            message="stale update",
            payload={},
            expected_version=case["version"],
        )


def test_trade_case_serializes_parallel_writes(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    case = create_trade_case(db_path, objective="Parallel sync", symbol="R_25")

    def write(artifact: str) -> str:
        updated = record_trade_case_artifact(
            db_path,
            case["id"],
            artifact_type=artifact,
            actor=artifact,
            message=f"{artifact} saved",
            payload={"artifact": artifact},
        )
        return str(updated["stage"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        stages = list(pool.map(write, ["advisor", "chart"]))

    restored = get_trade_case(db_path, case["id"])
    assert restored is not None
    assert restored["version"] == 3
    assert set(restored["context"]["artifacts"]) == {"advisor", "chart"}
    assert "market_validation" in stages


def test_preliminary_risk_can_be_saved_without_skipping_required_backtest(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    case = create_trade_case(db_path, objective="Preserve workflow order", symbol="R_75")
    case = record_trade_case_artifact(
        db_path,
        case["id"],
        artifact_type="market",
        actor="market",
        message="market saved",
        payload={"latest_close": 100},
    )
    case = record_trade_case_artifact(
        db_path,
        case["id"],
        artifact_type="risk",
        actor="risk",
        message="preliminary blockers saved",
        payload={"ok": False, "blockers": ["micro_strategy_not_run"]},
        advance_stage=False,
    )
    case = record_trade_case_artifact(
        db_path,
        case["id"],
        artifact_type="workflow_run",
        actor="manager",
        message="backtest required",
        payload={"current_step": "micro_backtest"},
        target_stage="micro_backtest",
    )

    assert case["stage"] == "micro_backtest"
    assert case["context"]["artifacts"]["risk"]["payload"]["ok"] is False
