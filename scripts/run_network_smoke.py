#!/usr/bin/env python3
"""Read-only Deriv network smoke; never authenticates and never places orders."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import get_historical_candles, get_market_ticks  # noqa: E402


async def run(symbol: str) -> dict[str, object]:
    cases = []
    for name, call in [
        ("get_market_ticks", lambda: get_market_ticks(symbol, False)),
        ("get_historical_candles", lambda: get_historical_candles(symbol, 60, 5)),
    ]:
        started = time.perf_counter()
        try:
            payload = json.loads(await call())
        except Exception as exc:
            payload = {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}
        cases.append(
            {
                "tool": name,
                "observed_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "ok": bool(payload.get("ok")),
                "error": payload.get("error"),
            }
        )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixture": False,
        "network": "Deriv public WebSocket",
        "symbol": symbol,
        "authenticated": False,
        "write_tools_executed": False,
        "supports_decision_budget_claim": False,
        "cases": cases,
        "all_passed": all(bool(item["ok"]) for item in cases),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="R_100")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/evidence/network-smoke.json"
    )
    args = parser.parse_args()
    result = asyncio.run(run(args.symbol))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
