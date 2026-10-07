"""Pure compatibility planning and parameter parsing.

The application owns model calls, confirmation and trade execution.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal


Action = Literal["get_market_ticks", "get_historical_candles", "place_contract", "chat"]


DEFAULT_SYMBOL = "R_100"


DEFAULT_GRANULARITY = 60


DEFAULT_COUNT = 60


@dataclass(slots=True)
class ToolPlan:
    action: Action
    params: dict[str, Any]
    rationale: str


def extract_json_object(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def normalize_plan(data: dict[str, Any]) -> ToolPlan:
    action = data.get("action", "chat")
    if action not in {
        "get_market_ticks",
        "get_historical_candles",
        "place_contract",
        "chat",
    }:
        action = "chat"

    params = data.get("params") or {}
    if action == "get_market_ticks":
        params = {
            "symbol": str(params.get("symbol") or DEFAULT_SYMBOL),
            "subscribe": bool(params.get("subscribe", False)),
        }
    elif action == "get_historical_candles":
        params = {
            "symbol": str(params.get("symbol") or DEFAULT_SYMBOL),
            "granularity": int(params.get("granularity") or DEFAULT_GRANULARITY),
            "count": min(max(int(params.get("count") or DEFAULT_COUNT), 1), 1000),
        }
    elif action == "place_contract":
        raw_condition = params.get("condition")
        condition = normalize_condition(raw_condition) if raw_condition else None
        duration = int(params.get("duration") or 0)
        duration_unit = str(params.get("duration_unit") or "m")
        if duration <= 0:
            duration = 5
            duration_unit = "t"
        params = {
            "symbol": str(params.get("symbol") or DEFAULT_SYMBOL),
            "amount": float(params.get("amount") or 0),
            "contract_type": str(params.get("contract_type") or "").upper(),
            "duration": duration,
            "duration_unit": duration_unit,
            "condition": condition,
            "market_read": str(params.get("market_read") or "tick"),
            "auto_execute": bool(params.get("auto_execute", True)),
        }

    return ToolPlan(
        action=action,
        params=params,
        rationale=str(data.get("rationale") or "模型已生成工具调用计划。"),
    )


def normalize_condition(condition: Any) -> dict[str, Any] | None:
    if not isinstance(condition, dict):
        return None
    metric = str(condition.get("metric") or "latest_tick")
    operator = str(condition.get("operator") or "")
    if operator not in {">", ">=", "<", "<=", "=="}:
        return None
    try:
        value = float(condition.get("value"))
    except (TypeError, ValueError):
        return None
    return {"metric": metric, "operator": operator, "value": value}


def local_rule_plan(user_text: str) -> ToolPlan:
    symbol = extract_symbol(user_text)
    granularity = extract_granularity(user_text)
    count = extract_count(user_text)
    trade_intent = has_trade_intent(user_text)

    if trade_intent:
        amount = extract_amount(user_text)
        duration = extract_duration(user_text)
        duration_unit = extract_duration_unit(user_text)
        if duration <= 0:
            duration = 5
            duration_unit = "t"
        contract_type = extract_contract_type(user_text)
        missing = []
        if has_close_intent(user_text) and not extract_contract_id(user_text):
            missing.append("contract_id")
        if amount <= 0 and not has_close_intent(user_text):
            missing.append("amount/金额")
        if not contract_type:
            missing.append("contract_type/方向 CALL 或 PUT")
        if missing:
            return ToolPlan(
                action="chat",
                params={},
                rationale=f"交易指令缺少 {', '.join(missing)}。",
            )
        return ToolPlan(
            action="place_contract",
            params={
                "symbol": symbol,
                "amount": amount,
                "contract_type": contract_type,
                "duration": duration,
                "duration_unit": duration_unit,
                "condition": extract_condition(user_text),
                "market_read": "tick",
                "auto_execute": True,
            },
            rationale="本地规则识别为模拟交易指令。",
        )

    if any(keyword in user_text for keyword in ["K线", "k线", "蜡烛", "历史", "走势"]):
        return ToolPlan(
            action="get_historical_candles",
            params={"symbol": symbol, "granularity": granularity, "count": count},
            rationale="本地规则识别为 K 线数据查询。",
        )

    if any(keyword in user_text for keyword in ["最新", "行情", "报价", "tick", "价格"]):
        return ToolPlan(
            action="get_market_ticks",
            params={"symbol": symbol, "subscribe": False},
            rationale="本地规则识别为最新行情查询。",
        )

    return ToolPlan(
        action="chat",
        params={},
        rationale="没有识别到明确工具调用，进入普通说明。",
    )


def has_trade_intent(text: str) -> bool:
    lowered = text.lower()
    keywords = [
        "购买",
        "下单",
        "建仓",
        "开仓",
        "平仓",
        "买入",
        "交易",
        "买涨",
        "看涨",
        "做多",
        "上涨",
        "买跌",
        "看跌",
        "做空",
        "下跌",
        "call",
        "put",
        "order",
        "buy",
        "open",
        "close",
    ]
    return any(keyword in text for keyword in keywords) or any(keyword in lowered for keyword in keywords)


def extract_contract_type(text: str) -> str:
    call=bool(re.search(r'\bcall\b',text,re.IGNORECASE)) or any(word in text for word in ['买涨','看涨','做多','上涨'])
    put=bool(re.search(r'\bput\b',text,re.IGNORECASE)) or any(word in text for word in ['买跌','看跌','做空','下跌'])
    if call==put:
        return ''
    return 'CALL' if call else 'PUT'


def normalize_deriv_symbol(symbol: str) -> str:
    raw = symbol.strip()
    if not raw:
        return DEFAULT_SYMBOL
    upper = raw.upper()
    if upper == "STPRNG":
        return "stpRNG"
    if upper.startswith("FRX") and len(upper) == 9:
        return "frx" + upper[3:]
    return upper


def extract_symbol(text: str) -> str:
    symbol_match = re.search(
        r"\b(?:R_\d+|1HZ\d+V|BOOM\d+|CRASH\d+|JD\d+|RDBULL|RDBEAR|stpRNG|frx[A-Za-z]{6})\b",
        text,
        flags=re.IGNORECASE,
    )
    if symbol_match:
        return normalize_deriv_symbol(symbol_match.group(0))
    if "欧元" in text or "eurusd" in text.lower():
        return "frxEURUSD"
    return DEFAULT_SYMBOL


def extract_granularity(text: str) -> int:
    if "5分钟" in text or "5m" in text.lower():
        return 300
    if "1小时" in text or "一小时" in text or "1h" in text.lower():
        return 3600
    return 60


def extract_count(text: str) -> int:
    match = re.search(r"(\d+)\s*(?:根|条|个|count)", text, flags=re.IGNORECASE)
    if match:
        return min(max(int(match.group(1)), 1), 1000)
    return DEFAULT_COUNT


def extract_amount(text: str) -> float:
    patterns = [
        r"(?:金额|stake|amount)\s*[:：]?\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:美元|usd|美金)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return 0.0


def extract_contract_id(text: str) -> int | None:
    match = re.search(r"(?:contract[_\s-]?id|合同|合约|id)\s*[:：#]?\s*(\d{4,})", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def has_close_intent(text: str) -> bool:
    lowered = text.lower()
    return any(word in text for word in ["平仓", "卖出合约", "关闭合约"]) or any(
        word in lowered for word in ["close", "sell contract", "exit contract"]
    )


def extract_duration(text: str) -> int:
    match = re.search(r"(\d+)\s*(?:分钟|分|m\b|小时|h\b|tick|ticks|跳)", text, flags=re.IGNORECASE)
    if not match:
        return 0
    return int(match.group(1))


def extract_duration_unit(text: str) -> str:
    lowered = text.lower()
    if "tick" in lowered or "ticks" in lowered or "跳" in text:
        return "t"
    if "小时" in text or "h" in lowered:
        return "h"
    return "m"


def extract_condition(text: str) -> dict[str, Any] | None:
    patterns = [
        (r"(?:价格|报价|最新价|tick)?\s*(?:大于等于|不低于|高于等于)\s*(\d+(?:\.\d+)?)", ">="),
        (r"(?:价格|报价|最新价|tick)?\s*(?:小于等于|不高于|低于等于)\s*(\d+(?:\.\d+)?)", "<="),
        (r"(?:价格|报价|最新价|tick)?\s*(?:大于|高于|突破|超过)\s*(\d+(?:\.\d+)?)", ">"),
        (r"(?:价格|报价|最新价|tick)?\s*(?:小于|低于|跌破)\s*(\d+(?:\.\d+)?)", "<"),
        (r"(?:>|＞)\s*(\d+(?:\.\d+)?)", ">"),
        (r"(?:<|＜)\s*(\d+(?:\.\d+)?)", "<"),
    ]
    for pattern, operator in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return {"metric": "latest_tick", "operator": operator, "value": float(match.group(1))}
    return None
