#!/usr/bin/env python3
"""Offline policy replay by default. --live evaluates real Jev on synthetic fixtures."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from advisory_policy import build_state, decide
from evals.scenarios import CASES, snapshot
from jev_router import JEV_MODEL, MarketAssessment, assess_market


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send fixture state to TypeSafe using TYPESAFE_API_KEY")
    parser.add_argument("--model", default=JEV_MODEL)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    key = os.environ.get("TYPESAFE_API_KEY", "") if args.live else "offline-fixture"
    if args.live and not key:
        parser.error("--live requires TYPESAFE_API_KEY")
    records = []
    for case in CASES:
        state = build_state(case["question"], case["symbol"], snapshot(case["symbol"], quality=case.get("quality", "ready")), [], case["scene"], case.get("thesis", ""), 10)
        if not state["evidence"]["tick_current"]:
            assessment = MarketAssessment(None, "no_current_tick")
        elif args.live:
            assessment = assess_market(state, key, model=args.model, deadline_at=time.perf_counter() + 2)
        else:
            with patch("jev_router._request", return_value=case["reply"]):
                assessment = assess_market(state, key, deadline_at=time.perf_counter() + 2)
        decision = decide(state, assessment, "CALL", enabled=True)
        actual = [decision["stance"], decision["requested_path"]]
        records.append({"id": case["id"], "expected": case["expect"], "actual": actual, "matched": actual == case["expect"], "assessment": assessment.as_dict(), "reason": decision["reason"]})
    latencies = sorted(r["assessment"]["latency_ms"] for r in records if r["assessment"]["source"] in {"jev", "jev_error"})
    report = {"mode": "live_model_fixture_eval" if args.live else "offline_policy_replay", "meaning": "Small synthetic fixture set; not trading performance or production model calibration.", "matched": sum(r["matched"] for r in records), "total": len(records), "network_latency_ms": {"p50": statistics.median(latencies), "p95": latencies[max(0, math.ceil(.95 * len(latencies)) - 1)]} if args.live and latencies else None, "cases": records}
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n")
    print(encoded)
    return 0 if report["matched"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
