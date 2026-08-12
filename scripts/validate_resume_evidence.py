#!/usr/bin/env python3
"""Fail closed when resume evidence or runtime capabilities are inconsistent."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import web_app  # noqa: E402

ALLOWED_STATUSES = {"verified", "implemented_unverified", "unsupported"}
EXPECTED_MCP_CATEGORIES = {
    "market_data": {"get_market_ticks", "get_historical_candles"},
    "trade_execution": {"execute_simulated_trade", "close_open_contract"},
    "account_management": {"check_account_status", "get_open_contract_status"},
}


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def live_mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "description": item.description,
            "input_schema": item.inputSchema,
            "output_schema": item.outputSchema,
        }
        for item in await server.mcp.list_tools()
    ]


def validate(resume_path: Path, runtime_path: Path) -> list[str]:
    errors: list[str] = []
    resume = json.loads(resume_path.read_text(encoding="utf-8"))
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))

    claims = resume.get("claims") or []
    if len(claims) != 5:
        errors.append(f"expected 5 resume claims, found {len(claims)}")
    for index, claim in enumerate(claims):
        status = claim.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(f"claim {index} has invalid status: {status}")
        for required in [
            "resume_text",
            "code_locations",
            "verification_commands",
            "versions_and_hashes",
            "artifacts",
        ]:
            if not claim.get(required):
                errors.append(f"claim {index} missing {required}")

    graph = runtime.get("graph") or {}
    execution_roles = set(graph.get("execution_role_ids") or [])
    expected_execution = {
        "manager",
        "strategy",
        "market",
        "compliance",
        "risk",
        "chart",
        "execution",
        "report",
    }
    if execution_roles != expected_execution:
        errors.append(f"execution roles changed: {sorted(execution_roles)}")
    advisors = set(graph.get("advisor_parallel_role_ids") or [])
    if len(advisors) != 5 or graph.get("advisor_parallel_role_count") != len(advisors):
        errors.append("advisor role count/list mismatch")
    if graph.get("advisor_chief_node") != "synthesize":
        errors.append("Chief advisor node missing")

    edges = {tuple(item) for item in graph.get("execution_edges") or []}
    required_order = {
        ("market", "compliance"),
        ("compliance", "risk"),
        ("risk", "chart"),
        ("chart", "safety_gate"),
        ("safety_gate", "execution"),
    }
    if not required_order <= edges or ("risk", "compliance") in edges:
        errors.append("three-layer safety ordering changed")

    budget = runtime.get("decision_budget") or {}
    if budget.get("budget_range_seconds") != [4, 25]:
        errors.append("decision budget range is not 4-25 seconds")
    if budget.get("artificial_sleep_used") is not False:
        errors.append("offline benchmark must not use artificial sleep")
    if budget.get("fixture") is not True:
        errors.append("offline benchmark must be labelled fixture")
    if budget.get("supports_real_network_latency_claim") is not False:
        errors.append("fixture must not support real network latency claims")

    live_tools = asyncio.run(live_mcp_tools())
    live_names = {item["name"] for item in live_tools}
    expected_names = set().union(*EXPECTED_MCP_CATEGORIES.values())
    if runtime.get("mcp", {}).get("tool_count") != 6:
        errors.append("recorded FastMCP tool count is not exactly 6")
    if len(live_tools) != 6 or live_names != expected_names:
        errors.append(f"FastMCP tool surface changed: {sorted(live_names)}")
    if runtime.get("mcp", {}).get("schema_sha256") != sha256_json(live_tools):
        errors.append("recorded MCP schema hash does not match runtime enumeration")
    mcp_artifact_path = runtime_path.parent / "mcp-tools.json"
    if not mcp_artifact_path.exists():
        errors.append("generated MCP tool inventory is missing")
    else:
        mcp_artifact = json.loads(mcp_artifact_path.read_text(encoding="utf-8"))
        if mcp_artifact != runtime.get("mcp"):
            errors.append("MCP tool inventory differs from runtime evidence")

    safety = runtime.get("safety") or {}
    if safety.get("ordered_layers") != ["compliance", "risk", "execution"]:
        errors.append("recorded safety layers changed")
    if safety.get("hitl_default") is not True:
        errors.append("HITL is not enabled by default")
    if safety.get("live_execution_default") is not False:
        errors.append("live execution is not disabled by default")
    if safety.get("write_tools_executed") is not False:
        errors.append("evidence generation must never execute write tools")

    provider = runtime.get("provider_contract") or {}
    if set(provider.get("providers") or []) != {"OpenAI", "Anthropic", "DeepSeek"}:
        errors.append("provider contract no longer covers all three providers")
    if provider.get("real_provider_api_executed") is not False:
        errors.append("provider fixture falsely claims real API execution")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--resume-evidence",
        type=Path,
        default=ROOT / "docs/resume-evidence.json",
    )
    parser.add_argument(
        "--runtime-evidence",
        type=Path,
        default=ROOT / "docs/evidence/runtime-evidence.json",
    )
    args = parser.parse_args()
    errors = validate(args.resume_evidence, args.runtime_evidence)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    print(json.dumps({"ok": True, "claims": 5, "statuses": sorted(ALLOWED_STATUSES)}))


if __name__ == "__main__":
    main()
