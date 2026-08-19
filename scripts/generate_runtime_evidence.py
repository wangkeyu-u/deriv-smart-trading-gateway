#!/usr/bin/env python3
"""Recompute machine-readable resume evidence without placing an order."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import web_app  # noqa: E402


EXECUTION_ROLE_IDS = {
    "manager",
    "strategy",
    "market",
    "compliance",
    "risk",
    "chart",
    "execution",
    "report",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def graph_snapshot() -> dict[str, Any]:
    execution = web_app.build_execution_langgraph().get_graph()
    advisor = web_app.build_advisor_langgraph().get_graph()
    parent = web_app.build_gateway_parent_graph().get_graph()
    execution_nodes = set(execution.nodes)
    advisor_nodes = set(advisor.nodes)
    advisor_role_nodes = sorted(
        item for item in advisor_nodes if item.startswith("advisor_")
    )
    return {
        "execution_role_ids": sorted(EXECUTION_ROLE_IDS & execution_nodes),
        "execution_role_count": len(EXECUTION_ROLE_IDS & execution_nodes),
        "execution_control_nodes": sorted(
            execution_nodes - EXECUTION_ROLE_IDS - {"__start__", "__end__"}
        ),
        "execution_edges": sorted(
            [item.source, item.target] for item in execution.edges
        ),
        "advisor_parallel_role_ids": advisor_role_nodes,
        "advisor_parallel_role_count": len(advisor_role_nodes),
        "advisor_chief_node": "synthesize" if "synthesize" in advisor_nodes else None,
        "parent_nodes": sorted(parent.nodes),
        "parent_edges": sorted([item.source, item.target] for item in parent.edges),
    }


async def mcp_snapshot() -> dict[str, Any]:
    tools = await server.mcp.list_tools()
    rows = [
        {
            "name": item.name,
            "description": item.description,
            "input_schema": item.inputSchema,
            "output_schema": item.outputSchema,
        }
        for item in tools
    ]
    names = {item["name"] for item in rows}
    categories = {
        "market_data": sorted(names & {"get_market_ticks", "get_historical_candles"}),
        "trade_execution": sorted(names & {"execute_simulated_trade", "close_open_contract"}),
        "account_management": sorted(names & {"check_account_status", "get_open_contract_status"}),
    }
    return {
        "tool_count": len(rows),
        "tools": rows,
        "categories": categories,
        "schema_sha256": sha256_json(rows),
    }


def offline_fixture_benchmark() -> dict[str, Any]:
    """Measure orchestration overhead only; no network and no write tool."""
    st.session_state.clear()
    web_app.init_state()
    original_strategy = web_app.assign_task_to_strategy_agent
    original_report = web_app.assign_task_to_report_agent
    try:
        web_app.assign_task_to_strategy_agent = lambda *args, **kwargs: {
            "role": "Strategy Researcher",
            "ok": True,
            "fixture": True,
        }
        web_app.assign_task_to_report_agent = lambda *args, **kwargs: {
            "role": "Report Agent",
            "ok": True,
            "fixture": True,
        }
        runs = []
        for requested_budget in (4, 25):
            result = web_app.run_execution_langgraph(
                "FIXTURE_ONLY: explain graph architecture; no market or trade intent",
                budget_seconds=requested_budget,
            )
            evidence = dict(result.runtime_evidence or {})
            runs.append(
                {
                    "requested_budget_seconds": requested_budget,
                    "effective_budget_seconds": evidence.get("budget_seconds"),
                    "observed_elapsed_ms": evidence.get("observed_elapsed_ms"),
                    "timed_out": evidence.get("timed_out"),
                    "node_timings": evidence.get("node_timings"),
                    "graph_trace": evidence.get("graph_trace"),
                }
            )
    finally:
        web_app.assign_task_to_strategy_agent = original_strategy
        web_app.assign_task_to_report_agent = original_report
    return {
        "fixture": True,
        "fixture_scope": "offline orchestration only; no Deriv network, provider API, or order",
        "supports_real_network_latency_claim": False,
        "artificial_sleep_used": False,
        "budget_range_seconds": [
            web_app.MIN_DECISION_BUDGET_SECONDS,
            web_app.MAX_DECISION_BUDGET_SECONDS,
        ],
        "runs": runs,
    }


def version_snapshot(resume_pdf: Path) -> dict[str, Any]:
    packages = {}
    for name in [
        "langgraph",
        "mcp",
        "websockets",
        "streamlit",
        "openai",
        "anthropic",
        "pytest",
        "pytest-asyncio",
    ]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    files = {
        "resume_pdf": resume_pdf,
        "agent_prompts": ROOT / "agent_prompts.json",
        "requirements": ROOT / "requirements.txt",
    }
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": packages,
        "files": {
            key: {"path": str(path), "sha256": sha256_file(path)}
            for key, path in files.items()
        },
    }


def build_evidence(resume_pdf: Path) -> dict[str, Any]:
    graph = graph_snapshot()
    mcp = asyncio.run(mcp_snapshot())
    benchmark = offline_fixture_benchmark()
    versions = version_snapshot(resume_pdf)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/generate_runtime_evidence.py",
        "git": {
            "branch": git("branch", "--show-current"),
            "evidence_source_head": git("rev-parse", "HEAD"),
            "round1_tag_target": git("rev-parse", "codex/round1-complete^{}"),
            "original_main": git("rev-parse", "main"),
            "origin_main": git("rev-parse", "origin/main"),
        },
        "versions_and_hashes": versions,
        "graph": graph,
        "decision_budget": benchmark,
        "websocket": {
            "request_correlation": "req_id -> pending Future",
            "subscription_queue_maxsize": server.SUBSCRIPTION_QUEUE_MAXSIZE,
            "subscription_backlog_maxsize": server.SUBSCRIPTION_BACKLOG_MAXSIZE,
            "backpressure_policy": "drop_oldest",
            "backoff_base_seconds": 0.25,
            "backoff_cap_seconds": 2.0,
            "backoff_jitter_ratio": 0.2,
        },
        "provider_contract": {
            "providers": ["OpenAI", "Anthropic", "DeepSeek"],
            "manager_tool_contract_count": len(web_app.MANAGER_TOOLS),
            "real_provider_api_executed": False,
            "test_mode": "mock_provider_fixture",
            "business_runtime": "deterministic_langgraph_python",
        },
        "mcp": mcp,
        "safety": {
            "ordered_layers": ["compliance", "risk", "execution"],
            "hitl_default": bool(st.session_state.require_trade_confirmation),
            "live_execution_default": bool(st.session_state.allow_live_execution),
            "write_tools_executed": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--resume-pdf",
        type=Path,
        default=Path("/Users/wangkeyu/Downloads/123简历.pdf"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs/evidence/runtime-evidence.json",
    )
    parser.add_argument(
        "--mcp-output",
        type=Path,
        default=ROOT / "docs/evidence/mcp-tools.json",
    )
    args = parser.parse_args()
    evidence = build_evidence(args.resume_pdf.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.mcp_output.parent.mkdir(parents=True, exist_ok=True)
    args.mcp_output.write_text(
        json.dumps(evidence["mcp"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": sha256_file(args.output),
                "mcp_output": str(args.mcp_output),
                "mcp_sha256": sha256_file(args.mcp_output),
            }
        )
    )


if __name__ == "__main__":
    main()
