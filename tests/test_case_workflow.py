from __future__ import annotations

from case_workflow import trade_case_consistency_gate, trade_case_decision_snapshot, workflow_resume_step


def valid_inputs() -> tuple[dict, dict, dict, dict, dict]:
    case = {"symbol": "R_75", "context": {"artifacts": {}}}
    advisor = {"symbol": "R_75", "stance": "CALL", "confidence": 0.72}
    market = {
        "symbol": "R_75",
        "candle_count": 120,
        "integrity": {"ok": True, "fresh": True},
    }
    micro = {
        "config": {"symbol": "R_75", "max_trade_amount": 1.0},
        "decision": {"action": "CALL"},
        "budget_guard": {"ok": True},
        "backtest": {"summary": {"trade_count": 7, "win_rate": 0.57, "total_pnl": 0.01, "halted": False}},
    }
    pending = {
        "symbol": "R_75",
        "contract_type": "CALL",
        "amount": 1.0,
        "allow_live": False,
    }
    return case, advisor, market, micro, pending


def test_consistency_gate_accepts_aligned_safe_evidence() -> None:
    case, advisor, market, micro, pending = valid_inputs()
    result = trade_case_consistency_gate(
        case,
        advisor=advisor,
        market=market,
        micro=micro,
        pending_trade=pending,
    )
    assert result["ok"] is True
    assert result["blockers"] == []


def test_consistency_gate_reports_symbol_direction_and_freshness_conflicts() -> None:
    case, advisor, market, micro, pending = valid_inputs()
    market["symbol"] = "R_100"
    market["integrity"]["fresh"] = False
    micro["decision"]["action"] = "PUT"
    result = trade_case_consistency_gate(
        case,
        advisor=advisor,
        market=market,
        micro=micro,
        pending_trade=pending,
    )
    assert result["ok"] is False
    assert "symbol_mismatch" in result["blockers"]
    assert "market_data_unhealthy" in result["blockers"]
    assert "direction_conflict" in result["blockers"]


def test_workflow_resume_step_uses_persisted_failure() -> None:
    case = {
        "context": {
            "artifacts": {
                "workflow_run": {
                    "payload": {
                        "completed_steps": ["advisor"],
                        "failed_step": "market",
                    }
                }
            }
        }
    }
    assert workflow_resume_step(case) == "market"


def test_consistency_gate_treats_completed_trade_cap_as_warning() -> None:
    case, advisor, market, micro, pending = valid_inputs()
    micro["backtest"]["summary"].update({"halted": True, "halt_reason": "max_trade_count"})

    result = trade_case_consistency_gate(
        case,
        advisor=advisor,
        market=market,
        micro=micro,
        pending_trade=pending,
    )

    assert result["ok"] is True
    assert "paper_trade_cap_reached" in result["warnings"]


def test_consistency_gate_does_not_call_wait_a_direction_conflict() -> None:
    case, advisor, market, micro, _pending = valid_inputs()
    advisor["stance"] = "WAIT"
    micro["decision"]["action"] = "PUT"

    result = trade_case_consistency_gate(
        case,
        advisor=advisor,
        market=market,
        micro=micro,
        pending_trade=None,
    )

    assert result["ok"] is False
    assert result["blockers"] == ["advisor_not_actionable"]


def test_decision_snapshot_rebuilds_operator_evidence_from_case() -> None:
    case = {
        "id": "TC-1",
        "status": "active",
        "stage": "risk_review",
        "symbol": "R_75",
        "context": {
            "artifacts": {
                "advisor": {"payload": {"stance": "PUT", "confidence": 0.71}},
                "market": {
                    "payload": {
                        "latest_close": 101.25,
                        "latest_timestamp": "2026-06-14T00:00:00Z",
                        "candle_count": 120,
                        "integrity": {"ok": True, "fresh": True},
                    }
                },
                "micro_strategy": {
                    "payload": {
                        "decision": {"action": "PUT", "confidence": 0.82},
                        "budget_guard": {"ok": True, "reason": "within_budget"},
                        "backtest": {
                            "summary": {
                                "trade_count": 6,
                                "wins": 4,
                                "losses": 2,
                                "win_rate": 2 / 3,
                                "total_pnl": 0.013,
                                "halted": False,
                            }
                        },
                    }
                },
                "risk": {"payload": {"ok": True, "blockers": [], "warnings": []}},
                "workflow_run": {
                    "payload": {
                        "status": "awaiting_confirmation",
                        "current_step": "human_confirmation",
                    }
                },
                "pending_trade": {
                    "payload": {
                        "symbol": "R_75",
                        "contract_type": "PUT",
                        "amount": 1.0,
                        "duration": 5,
                        "duration_unit": "t",
                        "allow_live": False,
                    }
                },
            }
        },
    }

    snapshot = trade_case_decision_snapshot(case)

    assert snapshot["status"] == "awaiting_confirmation"
    assert snapshot["advisor"] == {"action": "PUT", "confidence": 0.71, "consensus": None}
    assert snapshot["market"]["candle_count"] == 120
    assert snapshot["strategy"]["budget_ok"] is True
    assert snapshot["paper"]["trade_count"] == 6
    assert snapshot["pending"]["action"] == "PUT"
