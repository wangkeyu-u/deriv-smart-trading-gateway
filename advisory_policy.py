"""Scenario/evidence policy, independent of Streamlit, model vendors and execution."""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

from jev_router import MarketAssessment
from domain.market import ObservedTrend, legacy_observation

SCENES = {
    "observe": ("快速看盘", "Quick observation"),
    "review": ("交易想法复核", "Review a thesis"),
    "research": ("深入研究", "Deeper research"),
}
POLICY_VERSION = "advisory-v3"
THRESHOLD_STATUS = "UNCALIBRATED_THRESHOLD"


def number(value: Any) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value)


def instrument_profile(symbol: str) -> dict[str, Any]:
    upper = symbol.upper()
    if re.fullmatch(r"(?:R_\d+|1HZ\d+V|(?:BOOM|CRASH)\d+|JD\d+|RDBEAR|RDBULL|stpRNG)", symbol, re.IGNORECASE):
        family = "synthetic"
    elif re.fullmatch(r"FRX[A-Z]{6}", upper):
        family = "forex"
    else:
        family = "unknown"
    return {"family": family, "news_applicable": family == "forex", "directional_interpretation_allowed": family == "forex"}


def tick_is_current(market: dict[str, Any], now: float | None = None) -> bool:
    tick = market.get("tick")
    if not isinstance(tick, dict):
        return False
    quote, epoch = number(tick.get("quote")), number(tick.get("epoch"))
    if quote is None or quote <= 0 or epoch is None:
        return False
    if tick.get("symbol") and market.get("symbol") and tick["symbol"] != market["symbol"]:
        return False
    return 0 <= (time.time() if now is None else now) - epoch <= 30


def _timestamp(value: Any) -> float:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("ambiguous timestamp")
        return parsed.timestamp()
    result = number(value)
    if result is None:
        raise ValueError("missing timestamp")
    return result


def market_evidence(market: dict[str, Any], symbol: str, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    tick = market.get("tick") if isinstance(market.get("tick"), dict) else {}
    current = tick_is_current({**market, "symbol": symbol}, now)
    epoch = number(tick.get("epoch"))
    result: dict[str, Any] = {
        "tick_current": current,
        "tick_age_seconds": round(now - epoch, 2) if epoch is not None else None,
        "quote": number(tick.get("quote")),
        "candles_current": False,
        "candle_count": 0,
        "trend": ObservedTrend.UNKNOWN,
        "status": "no_current_tick" if not current else "insufficient_candles",
    }
    raw = market.get("candles") or {}
    if not isinstance(raw, dict) or not raw.get("ok"):
        return result
    data = raw.get("data") or {}
    if data.get("symbol") and data["symbol"] != symbol:
        result["status"] = "symbol_mismatch"
        return result
    rows = data.get("ohlcv")
    if not isinstance(rows, list) or not rows:
        return result
    try:
        closes, stamps = [], []
        for row in rows:
            prices = [number(row.get(key)) for key in ("open", "high", "low", "close")]
            if any(value is None or value <= 0 for value in prices):
                raise ValueError("invalid price")
            opening, high, low, close = prices
            if not low <= min(opening, close) <= max(opening, close) <= high:
                raise ValueError("invalid OHLC")
            closes.append(close)
            stamps.append(_timestamp(row.get("timestamp")))
        # These are 60-second candles. Reject duplicates, gaps and reversed input.
        if any(abs(b - a - 60) > 1 for a, b in zip(stamps, stamps[1:])):
            raise ValueError("non-contiguous candles")
        result["candle_count"] = len(closes)
        result["candle_age_seconds"] = round(now - stamps[-1], 2)
        if len(closes) < 20:
            return result
        if not 0 <= now - stamps[-1] <= 120:
            result["status"] = "stale_candles" if current else "no_current_tick"
            return result
        ma5, ma20 = sum(closes[-5:]) / 5, sum(closes[-20:]) / 20
        trend = ObservedTrend.UP if closes[-1] > closes[0] and ma5 > ma20 else ObservedTrend.DOWN if closes[-1] < closes[0] and ma5 < ma20 else ObservedTrend.FLAT
        result.update(candles_current=True, trend=trend, ma5=ma5, ma20=ma20, latest_close=closes[-1], change_pct=(closes[-1] / closes[0] - 1) * 100, window_minutes=len(closes), status="ready" if current else "no_current_tick")
    except (ValueError, TypeError, AttributeError, OverflowError):
        result["status"] = "invalid_candles" if current else "no_current_tick"
    return result


def relevant_news(sources: list[dict[str, Any]], symbol: str, now: float | None = None) -> list[dict[str, Any]]:
    if not instrument_profile(symbol)["news_applicable"]:
        return []
    now = time.time() if now is None else now
    fresh = []
    for source in sources:
        try:
            stamp = parsedate_to_datetime(str(source.get("published") or ""))
            if stamp.tzinfo is None:
                continue
            age = now - stamp.timestamp()
            if not 0 <= age <= 86400:
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        fresh.append({**source, "age_hours": round(age / 3600, 2)})
    return fresh[:8]


def build_state(question: str, symbol: str, market: dict[str, Any], sources: list[dict[str, Any]], scene: str, thesis: str, remaining: float) -> dict[str, Any]:
    profile = instrument_profile(symbol)
    evidence = market_evidence(market, symbol)
    return {
        "policy_version": POLICY_VERSION,
        "threshold_status": THRESHOLD_STATUS,
        "scene": scene,
        "question": question[:800],
        "thesis_direction": (legacy_observation(thesis).value if thesis in {"CALL", "PUT"} else thesis) if scene == "review" else "not_requested",
        "symbol": symbol,
        "instrument": profile,
        "evidence": evidence,
        "news": [{"title": str(s.get("title") or "")[:180], "published": s.get("published"), "age_hours": s.get("age_hours")} for s in relevant_news(sources, symbol)[:3]],
        "news_role": "context_only_not_directional_signal" if profile["news_applicable"] else "not_applicable",
        "remaining_budget": "explanation_possible" if remaining >= 2.5 else "short_result_only",
        "synthetic_strategy_validated": False,
    }


def decide(state: dict[str, Any], assessment: MarketAssessment, local_stance: str, *, enabled: bool) -> dict[str, Any]:
    evidence = state["evidence"]
    scene = state["scene"]
    stance, path, reason = "UNKNOWN", "wait", "no_current_tick"
    valid_model = assessment.source == "jev"
    if evidence["tick_current"]:
        path = "deep" if scene == "research" else "finish"
        reason = "local_observation"
        if evidence["status"] == "ready" and state["instrument"]["directional_interpretation_allowed"]:
            stance = local_stance
        if valid_model:
            path_prob = assessment.path_probabilities.get(assessment.reasoning_path or "", 0)
            if path_prob < 0.8 or (assessment.path_confidence or 0) < 0.7:
                path, stance, reason = "deep", "UNKNOWN", "uncertain_path"
            elif assessment.reasoning_path == "wait":
                path, stance, reason = "wait", "UNKNOWN", "jev_needs_evidence"
            else:
                path = "deep" if scene == "research" else str(assessment.reasoning_path)
                reason = "research_requested" if scene == "research" else "jev_" + path
                selected = (assessment.probabilities or {}).get(assessment.stance or "", 0)
                supported = {"UP": "UP", "DOWN": "DOWN", "FLAT": "FLAT"}.get(evidence["trend"], "UNKNOWN")
                if selected >= 0.8 and (assessment.confidence or 0) >= 0.7 and evidence["status"] == "ready" and state["instrument"]["directional_interpretation_allowed"]:
                    candidate = assessment.stance or "UNKNOWN"
                    stance = candidate if candidate == supported and local_stance in {candidate, "UNKNOWN"} else "UNKNOWN"
                else:
                    stance = "UNKNOWN"
                if scene == "review":
                    thesis_ok = assessment.thesis_status == "supported" and assessment.thesis_probabilities.get("supported", 0) >= 0.8 and (assessment.thesis_confidence or 0) >= 0.7
                    if not thesis_ok or stance != state["thesis_direction"]:
                        stance = "UNKNOWN"
        elif enabled:
            stance = "UNKNOWN"
            path = "deep" if assessment.source == "jev_error" else "wait"
            reason = assessment.error_code or assessment.source
        elif scene == "review":
            stance, reason = "UNKNOWN", "thesis_requires_review"
    direction_reason = "observed_window"
    if evidence["status"] != "ready":
        stance, path, reason = "UNKNOWN", "wait", evidence["status"]
        direction_reason = evidence["status"]
    elif not state["instrument"]["directional_interpretation_allowed"]:
        stance, direction_reason = "UNKNOWN", "descriptive_only"
    elif stance == "UNKNOWN":
        direction_reason = "thesis_not_supported" if scene == "review" else "direction_not_supported"
    return {"direction_reason": direction_reason, "requested_path": path, "reason": reason, "stance": "WAIT", "observed_trend": stance, "evidence_id": hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()[:16], "policy_version": POLICY_VERSION}


REASONS = {
    "observed_window": ("方向仅描述已发生的观察窗口", "Direction describes the observed window only"),
    "descriptive_only": ("此品种只展示观察，尚无已验证的方向策略", "Descriptive observation; no validated directional strategy"),
    "thesis_not_supported": ("交易想法未获得充分且一致的证据支持", "The thesis lacks sufficient consistent support"),
    "direction_not_supported": ("方向判断不确定或与证据冲突", "Direction is uncertain or conflicts with evidence"),
    "insufficient_candles": ("有效 K 线不足 20 根", "Fewer than 20 valid candles"),
    "stale_candles": ("K 线时间已过期", "Candle data is stale"),
    "invalid_candles": ("K 线缺失、不连续或价格无效", "Missing, non-contiguous or invalid candles"),
    "symbol_mismatch": ("行情品种不匹配", "Instrument mismatch"),
    "graph_error": ("分析流程未完成", "Analysis did not complete"),
    "request_invalid": ("TypeSafe 拒绝了请求格式", "TypeSafe rejected the request format"),
    "http_error": ("TypeSafe 服务请求失败", "TypeSafe service request failed"),
    "no_current_tick": ("缺少带有效时间的新鲜报价", "No fresh timestamped quote"),
    "jev_needs_evidence": ("Jev 判断需要先补证据", "Jev requested more evidence"),
    "uncertain_path": ("Jev 对下一步判断不确定", "Jev path is uncertain"),
    "research_requested": ("本轮明确要求深入研究", "Research was requested"),
    "jev_finish": ("Jev 判断现有证据足以给出简短结论", "Jev chose a concise result"),
    "jev_deep": ("Jev 判断问题需要进一步解释", "Jev requested deeper explanation"),
    "local_observation": ("依据本地证据完成观察", "Local evidence observation"),
    "thesis_requires_review": ("交易想法尚未经过模型复核", "Thesis has not been reviewed by a model"),
    "deadline": ("剩余时间不足", "Time budget exhausted"),
    "disabled": ("Jev 未启用或尚未配置密钥", "Jev disabled or missing a key"),
    "timeout": ("Jev 请求达到时间上限", "Jev timed out"),
    "authentication": ("TypeSafe 密钥验证失败", "TypeSafe authentication failed"),
    "rate_limited": ("TypeSafe 请求限流", "TypeSafe rate limited the request"),
    "overloaded": ("TypeSafe 服务繁忙", "TypeSafe is overloaded"),
    "invalid_response": ("Jev 返回的数据未通过校验", "Jev response failed validation"),
    "network": ("Jev 网络请求失败", "Jev network request failed"),
}


def reason_text(reason: str, language: str = "zh") -> str:
    values = REASONS.get(reason, ("本轮模型服务未完成", "Model service did not complete"))
    return values[0 if language == "zh" else 1]
