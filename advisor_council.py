"""Advisor council: multi-advisor voting and synthesis logic.

Extracted from agent_streaming.py to keep the streaming runtime focused on
orchestration while the council logic (voting, local fallbacks, JSON parsing)
lives in one testable place.
"""

from __future__ import annotations

import json
import re
from typing import Any


# ---------------------------------------------------------------------------
# Advisor identification & parsing
# ---------------------------------------------------------------------------
def is_advisor(agent_id: str) -> bool:
    """Check if an agent is an advisor (part of the council)."""
    return agent_id.startswith("advisor.")


def parse_advisor_json(report: str) -> dict[str, Any] | None:
    """Try to parse an advisor's JSON report. Returns None on failure."""
    if not report:
        return None
    # Try direct parse first
    try:
        return json.loads(report)
    except json.JSONDecodeError:
        pass
    # Try to extract JSON block from markdown
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", report, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return None


# ---------------------------------------------------------------------------
# Chief synthesis (local fallback)
# ---------------------------------------------------------------------------
def local_chief_synthesis(
    advisor_reports: dict[str, str],
    symbol: str,
    language: str = "zh",
) -> str:
    """Local fallback: synthesize advisor reports into a chief conclusion."""
    stances: dict[str, int] = {"CALL": 0, "PUT": 0, "WAIT": 0, "BLOCK": 0}
    parsed_count = 0

    for agent_id, report in advisor_reports.items():
        if not is_advisor(agent_id) or agent_id == "advisor.chief":
            continue
        parsed = parse_advisor_json(report)
        if parsed and "stance" in parsed:
            stances[parsed["stance"]] = stances.get(parsed["stance"], 0) + 1
            parsed_count += 1

    if parsed_count == 0:
        # Fallback to text heuristics
        for report in advisor_reports.values():
            upper = report.upper()
            if "CALL" in upper:
                stances["CALL"] += 1
            elif "PUT" in upper:
                stances["PUT"] += 1
            elif "BLOCK" in upper:
                stances["BLOCK"] += 1
            else:
                stances["WAIT"] += 1

    winner, confidence = _tally_votes(stances)

    if language == "en":
        return json.dumps({
            "advisor": "chief",
            "stance": winner,
            "confidence": round(confidence, 2),
            "vote_breakdown": stances,
            "winning_side": winner,
            "dissent": "See individual advisor reports",
            "reasoning": f"Synthesized from {parsed_count} advisor votes",
            "preconditions": ["human_confirmation", "market_stability"],
            "invalidation": "If any advisor's preconditions are not met",
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "advisor": "chief",
        "stance": winner,
        "confidence": round(confidence, 2),
        "vote_breakdown": stances,
        "winning_side": winner,
        "dissent": "见各谋士报告",
        "reasoning": f"基于 {parsed_count} 位谋士投票综合得出",
        "preconditions": ["人工确认", "行情稳定"],
        "invalidation": "任一谋士前提条件未满足时结论失效",
    }, ensure_ascii=False, indent=2)


def _tally_votes(stances: dict[str, int]) -> tuple[str, float]:
    """Determine the winning stance and confidence from a vote tally."""
    if stances.get("BLOCK", 0) > 0:
        return "WAIT", 0.3
    total = max(1, sum(stances.values()))
    if stances["CALL"] > stances["PUT"] and stances["CALL"] > stances["WAIT"]:
        return "CALL", min(0.75, stances["CALL"] / total)
    if stances["PUT"] > stances["CALL"] and stances["PUT"] > stances["WAIT"]:
        return "PUT", min(0.75, stances["PUT"] / total)
    return "WAIT", 0.5


# ---------------------------------------------------------------------------
# Local advisor reports (data-driven, no LLM needed)
# ---------------------------------------------------------------------------
def local_advisor_report(
    agent_id: str,
    symbol: str,
    market: dict[str, Any] | None,
    language: str = "zh",
) -> str | None:
    """Generate a local (no-LLM) advisor report.

    Returns None if agent_id is not an advisor.
    """
    if not is_advisor(agent_id):
        return None

    change = (market or {}).get("window_change_pct")
    closes = (market or {}).get("closes") or []

    ma5 = round(sum(closes[-5:]) / len(closes[-5:]), 4) if len(closes) >= 5 else None
    ma20 = round(sum(closes[-20:]) / len(closes[-20:]), 4) if len(closes) >= 20 else None

    volatility_pct = None
    if len(closes) >= 21:
        returns = [(closes[i] / closes[i - 1] - 1) for i in range(-20, 0)]
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        volatility_pct = round((variance ** 0.5) * 100, 4)

    builders = {
        "advisor.macro": _build_macro,
        "advisor.quant": _build_quant,
        "advisor.flow": _build_flow,
        "advisor.risk": _build_risk,
        "advisor.contrarian": _build_contrarian,
        "advisor.chief": _build_chief_pending,
    }
    builder = builders.get(agent_id)
    if builder is None:
        return None
    return builder(
        symbol=symbol,
        change=change,
        ma5=ma5,
        ma20=ma20,
        volatility_pct=volatility_pct,
        language=language,
    )


def _build_macro(*, symbol: str, change, ma5, ma20, volatility_pct, language: str) -> str:
    return json.dumps({
        "advisor": "macro", "stance": "WAIT", "confidence": 0.35,
        "catalysts": [], "macro_bias": "neutral",
        "reasoning": "No external news feed; macro view deferred" if language == "en" else "无外部新闻源，宏观判断暂缓",
        "preconditions": ["news_catalyst"],
    }, ensure_ascii=False)


def _build_quant(*, symbol: str, change, ma5, ma20, volatility_pct, language: str) -> str:
    ma_signal = "golden_cross" if (ma5 and ma20 and ma5 > ma20) else "death_cross" if (ma5 and ma20 and ma5 < ma20) else "neutral"
    stance = "CALL" if ma_signal == "golden_cross" else "PUT" if ma_signal == "death_cross" else "WAIT"
    return json.dumps({
        "advisor": "quant", "stance": stance,
        "confidence": 0.55, "ma5": ma5, "ma20": ma20, "ma_signal": ma_signal,
        "momentum": "strong" if abs(change or 0) > 0.5 else "weak",
        "volatility": "medium",
        "reasoning": f"MA5={'above' if ma5 and ma20 and ma5 > ma20 else 'below'} MA20, change={change or 0:.3f}%",
        "preconditions": ["ma_cross_confirmed"],
    }, ensure_ascii=False)


def _build_flow(*, symbol: str, change, ma5, ma20, volatility_pct, language: str) -> str:
    flow_stance = "CALL" if (change or 0) > 0.3 else "PUT" if (change or 0) < -0.3 else "WAIT"
    flow_conf = min(0.7, abs(change or 0) / 2.0) if change else 0.3
    return json.dumps({
        "advisor": "flow", "stance": flow_stance, "confidence": round(flow_conf, 2),
        "tick_speed": "fast" if abs(change or 0) > 1.0 else "normal",
        "flow_pressure": "buy_pressure" if (change or 0) > 0 else "sell_pressure" if (change or 0) < 0 else "balanced",
        "entry_window": "now" if abs(change or 0) > 0.5 else "wait_5min",
        "reasoning": f"Window change {change or 0:.3f}% indicates {flow_stance}" if language == "en" else f"窗口变化 {change or 0:.3f}% 指向 {flow_stance}",
        "preconditions": ["tick_stream_stable"] if flow_stance != "WAIT" else ["wait_for_clearer_signal"],
    }, ensure_ascii=False)


def _build_risk(*, symbol: str, change, ma5, ma20, volatility_pct, language: str) -> str:
    vol_ok = volatility_pct is None or volatility_pct < 3.0
    if not vol_ok:
        risk_stance = "WAIT"
    elif (change or 0) > 0 and ma5 and ma20 and ma5 > ma20:
        risk_stance = "CALL"
    elif (change or 0) < 0 and ma5 and ma20 and ma5 < ma20:
        risk_stance = "PUT"
    else:
        risk_stance = "WAIT"
    return json.dumps({
        "advisor": "risk", "stance": risk_stance, "confidence": 0.5 if vol_ok else 0.3,
        "account_health": "healthy" if vol_ok else "warning",
        "max_affordable_loss": 1.0,
        "risk_reward_ratio": 1.8 if vol_ok else 0.8,
        "reasoning": f"Volatility {volatility_pct}% is {'acceptable' if vol_ok else 'too high'}" if language == "en" else f"波动率 {volatility_pct}% {'可接受' if vol_ok else '过高'}",
        "preconditions": ["demo_account_only", "max_loss_1usd"],
    }, ensure_ascii=False)


def _build_contrarian(*, symbol: str, change, ma5, ma20, volatility_pct, language: str) -> str:
    contrarian_stance = "PUT" if (change or 0) > 0.5 else "CALL" if (change or 0) < -0.5 else "WAIT"
    return json.dumps({
        "advisor": "contrarian", "stance": contrarian_stance, "confidence": 0.35,
        "consensus_challenge": "Trend may already be priced in" if language == "en" else "趋势可能已被价格吸收",
        "hidden_risks": ["momentum_exhaustion"] if abs(change or 0) > 1.0 else ["sample_too_small"],
        "reasoning": f"Counter-trend view against {change or 0:.3f}% move" if language == "en" else f"逆当前 {change or 0:.3f}% 走势",
        "preconditions": ["pullback_confirmation"],
    }, ensure_ascii=False)


def _build_chief_pending(*, symbol: str, change, ma5, ma20, volatility_pct, language: str) -> str:
    return json.dumps({
        "advisor": "chief", "stance": "WAIT", "confidence": 0.4,
        "vote_breakdown": {"CALL": 0, "PUT": 0, "WAIT": 0, "BLOCK": 0},
        "winning_side": "WAIT",
        "dissent": "Pending advisor inputs" if language == "en" else "待谋士输入",
        "reasoning": "Chief synthesis pending" if language == "en" else "首席汇总待定",
        "preconditions": ["advisor_votes"],
        "invalidation": "N/A",
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Council orchestration helpers
# ---------------------------------------------------------------------------
def extract_chief_conclusion(reports: dict[str, str]) -> dict[str, Any] | None:
    """Find and parse the chief advisor's conclusion from a reports dict.

    reports keys are display names (e.g. "首席谋士"), values are report strings.
    """
    for name, report in reports.items():
        if "首席" in name or "chief" in name.lower():
            return parse_advisor_json(report)
    return None


def extract_chief_stance(reports: dict[str, str]) -> str | None:
    """Return the chief's stance (CALL/PUT/WAIT) or None."""
    conclusion = extract_chief_conclusion(reports)
    if conclusion and conclusion.get("stance") in ("CALL", "PUT"):
        return conclusion["stance"]
    return None
