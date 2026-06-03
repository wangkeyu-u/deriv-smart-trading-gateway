"""Streamlit web interface for the Deriv Smart Trading Gateway.

Run:
    streamlit run web_app.py
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import math
import re
import sqlite3
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from server import (
    check_account_status,
    execute_simulated_trade,
    get_historical_candles,
    get_market_ticks,
    mask_secret,
)


Provider = Literal["本地规则", "OpenAI", "DeepSeek", "Anthropic", "OpenAI-Compatible"]
Action = Literal["get_market_ticks", "get_historical_candles", "execute_simulated_trade", "chat"]

DEFAULT_SYMBOL = "R_100"
DEFAULT_GRANULARITY = 60
DEFAULT_COUNT = 60
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "local_data"
DB_PATH = DATA_DIR / "gateway.sqlite3"
LOCAL_TZ = ZoneInfo("Asia/Kuala_Lumpur")

I18N = {
    "zh": {
        "sidebar_title": "Deriv Gateway",
        "sidebar_caption": "多智能体交易终端",
        "language": "语言",
        "security": "安全密钥配置",
        "deriv_token": "Deriv API Token",
        "llm_api": "大模型 API",
        "model": "模型",
        "connection": "连接状态",
        "clear_chat": "清空聊天记录",
        "hero_kicker": "层级多智能体交易网关",
        "hero_title": "Deriv Smart Trading Gateway",
        "hero_subtitle": "交易经理调度行情、策略、风控、合规、图表、执行和报告 Agent，完成实时行情读取、条件判断、模拟盘下单和可审计复盘。",
        "agent_team": "交易团队",
        "market_agent": "行情分析师",
        "market_agent_role": "读取 Tick/K 线，判断趋势与条件",
        "execution_agent": "执行交易员",
        "execution_agent_role": "条件满足后提交模拟盘订单",
        "swarm_graph": "动态智能体图谱",
        "swarm_graph_caption": "主 Agent 位于中心，外围 Agent 按任务流实时点亮。",
        "direct_dispatch": "老板直派子 Agent",
        "direct_agent": "选择子 Agent",
        "direct_task": "直接派活内容",
        "direct_task_placeholder": "例如：帮我重新检查 R_100 最近 30 个 Tick；或者给当前交易写一份风险复盘",
        "dispatch": "派活",
        "direct_done": "已完成直派任务",
        "chart_snapshots": "图表快照",
        "new_chart": "新建图表",
        "no_chart_snapshots": "还没有图表快照。可以让图表工程师生成，也可以直接加载默认图表。",
        "snapshot_time": "生成时间",
        "sync_bus": "实时同步总线",
        "sync_bus_hint": "API 调用、Agent 事件、图谱状态、图表快照都写入这里。",
        "api_trace": "API 调用 Trace",
        "sync_version": "同步版本",
        "chat_title": "交易经理指令台",
        "chat_caption": "输入自然语言目标，经理会自动派活给两个子 Agent。",
        "command_title": "交易指令工作台",
        "command_hint": "Enter 只用于中文输入法确认或换行；点击发送按钮才会提交。",
        "send": "发送指令",
        "clear_input": "清空输入",
        "clear_input_short": "清空",
        "send_note": "不会因为 Enter 自动发送，适合中文输入法选词。",
        "agent_log": "智能体自动执行日志",
        "results": "实时交易工作台",
        "results_hint": "K 线图、订单回执、子 Agent 状态和最新 tick 会在这里显示。",
        "load_default": "加载 R_100 最近 120 根 1分钟K线",
        "history": "本地历史",
        "active": "运行中",
        "standby": "待命",
        "market_default_bubble": "我负责看盘。你发出指令后，我会去读取最新 Tick 或 K 线，并用简单话汇报趋势和触发条件。",
        "execution_default_bubble": "我负责风控和下单。只有条件满足、参数齐全、Token 已配置时，我才会提交 Deriv 模拟盘订单并保存回执。",
        "market_task_prefix": "收到任务",
        "market_report_prefix": "我刚查完",
        "execution_task_prefix": "收到执行任务",
        "execution_report_prefix": "执行结果",
        "chat_placeholder": "例如：帮我看看 R_100，如果连续三个 Tick 都在跌，就用 10 美金买个看涨，持续 5 ticks。\n或者：画 R_100 最近 120 根 1分钟K线",
        "team_processing": "交易团队正在协同处理您的指令...",
        "team_done": "交易团队协同完成",
        "team_blocked": "交易团队处理完成，但存在阻断项",
        "structured_result": "团队结构化结果",
        "empty_command": "请输入一条交易指令。",
        "local_db": "本地数据",
        "db_path": "SQLite 保存路径",
        "chart_workbench": "交易图工作台",
        "no_candles": "还没有 K 线数据。可以通过聊天指令生成，也可以直接加载默认 R_100 图表。",
        "latest_tick": "最新 Tick",
        "live_results": "实时结果",
        "initial_message": "你好，我可以帮你查 Deriv 行情、画 K 线，或基于已配置的 Deriv Token 执行模拟交易。",
        "default_log": "等待交易指令。这里会显示：数据读取 -> 条件判断 -> 自动触发下单 的完整执行链。",
        "token_placeholder": "粘贴 Deriv demo/live token",
        "token_help": "只保存在当前 Streamlit Session 状态中，不会硬编码到文件。",
        "provider_help": "DeepSeek 和其它 OpenAI-compatible 服务会通过 OpenAI SDK 的 base_url 模式调用。",
        "local_rule_info": "当前使用本地规则解析，不需要大模型 API Key。",
        "compatible_key_placeholder": "粘贴兼容 OpenAI API 的服务 Key",
        "api_key_help": "只保存在当前 Streamlit Session 状态中，不会写入源码或配置文件。",
        "manual_model": "手动输入其它模型名",
        "custom_model": "自定义模型名",
        "base_url_help": "填写兼容 OpenAI Chat Completions 的 base_url。",
        "not_configured": "未配置",
        "not_configured_or_not_needed": "未配置/不需要",
        "model_api": "模型 API",
        "model_key": "模型 Key",
        "model_name": "模型名",
        "chart_note": "支持滚轮缩放、框选放大、拖拽平移、悬浮十字读数、画线/画框/画圆/自由路径标注、擦除标注和导出 PNG。图表右上角工具栏里可以切换这些操作。",
        "chart_height": "图表高度",
        "compare_trend": "叠加对比走势",
        "compare_symbol": "对比 Symbol",
        "compare_placeholder": "例如 R_75 / frxEURUSD",
        "refresh_current": "刷新当前 K 线",
        "refresh_compare": "加载/刷新对比",
        "measure": "测量",
        "start_candle": "起点 K 线",
        "end_candle": "终点 K 线",
        "measure_hint": "选择两根不同的 K 线来测量价格和时间差。",
        "bar_count": "K 线数量",
        "time_span": "时间跨度",
        "close_delta": "收盘差值",
        "range_amplitude": "区间振幅",
        "measure_data": "测量、区间分析和完整数据",
        "full_ohlcv": "完整 OHLCV",
        "download_ohlcv": "下载 OHLCV CSV",
        "download_log": "下载执行日志",
        "success_badge": "绿色成功勋章 · Deriv 订单回执已确认",
        "chart_empty_info": "还没有可绘制的 K 线数据。先输入：画 R_100 最近 60 根 1分钟K线",
        "chart_title_suffix": "K 线交易图",
        "local_provider_label": "本地规则",
        "example_tick": "查 R_100 最新价",
        "example_candles": "画 R_100 最近 120 根 1分钟K线",
        "example_trade": "10 美金看涨 · 5 ticks",
    },
    "en": {
        "sidebar_title": "Deriv Gateway",
        "sidebar_caption": "Multi-agent trading terminal",
        "language": "Language",
        "security": "Secure Credentials",
        "deriv_token": "Deriv API Token",
        "llm_api": "Model API",
        "model": "Model",
        "connection": "Connection",
        "clear_chat": "Clear Chat",
        "hero_kicker": "Hierarchical Multi-Agent Trading Gateway",
        "hero_title": "Deriv Smart Trading Gateway",
        "hero_subtitle": "A trading manager coordinates a market analyst and a risk execution agent for market reads, condition checks, demo execution, and auditable receipts.",
        "agent_team": "Trading Team",
        "market_agent": "Market Analyst",
        "market_agent_role": "Reads ticks/candles and validates market conditions",
        "execution_agent": "Risk Execution Agent",
        "execution_agent_role": "Checks account state and executes demo orders",
        "swarm_graph": "Dynamic Agent Graph",
        "swarm_graph_caption": "The main agent sits in the center; worker agents light up as tasks flow.",
        "direct_dispatch": "Boss-to-Agent Dispatch",
        "direct_agent": "Choose Sub-Agent",
        "direct_task": "Direct Task",
        "direct_task_placeholder": "Example: Recheck the latest 30 R_100 ticks; or write a risk recap for the current trade.",
        "dispatch": "Dispatch",
        "direct_done": "Direct task completed",
        "chart_snapshots": "Chart Snapshots",
        "new_chart": "New Chart",
        "no_chart_snapshots": "No chart snapshots yet. Ask the Chart Engineer to create one or load the default chart.",
        "snapshot_time": "Generated",
        "sync_bus": "Live Sync Bus",
        "sync_bus_hint": "API calls, agent events, graph state, and chart snapshots all write here.",
        "api_trace": "API Trace",
        "sync_version": "Sync Version",
        "chat_title": "Trading Manager Console",
        "chat_caption": "Enter a natural-language goal; the manager delegates work to two sub-agents.",
        "command_title": "Order Command Pad",
        "command_hint": "Enter only confirms IME text or inserts a new line; click Send to submit.",
        "send": "Send Order",
        "clear_input": "Clear Input",
        "clear_input_short": "Clear",
        "send_note": "Enter will not auto-send, so IME composition is safe.",
        "agent_log": "Agent Execution Log",
        "results": "Live Trading Workbench",
        "results_hint": "Candles, receipts, sub-agent state, and latest ticks appear here.",
        "load_default": "Load R_100 · 120 candles · 1m",
        "history": "Local History",
        "active": "Active",
        "standby": "Standby",
        "market_default_bubble": "I watch the market. Once you send an order goal, I will read the latest ticks or candles and report trend conditions in plain language.",
        "execution_default_bubble": "I handle risk checks and execution. I only submit a Deriv demo order when conditions pass, parameters are complete, and a token is configured.",
        "market_task_prefix": "Task received",
        "market_report_prefix": "Market check done",
        "execution_task_prefix": "Execution task received",
        "execution_report_prefix": "Execution result",
        "chat_placeholder": "Example: Check R_100. If the last three ticks are falling, buy a 10 USD CALL for 5 ticks.\nOr: Draw the latest 120 one-minute candles for R_100.",
        "team_processing": "The trading team is coordinating your request...",
        "team_done": "Trading team completed",
        "team_blocked": "Trading team finished with a blocker",
        "structured_result": "Structured Team Result",
        "empty_command": "Please enter a trading command.",
        "local_db": "Local Data",
        "db_path": "SQLite path",
        "chart_workbench": "Trading Chart Workbench",
        "no_candles": "No candle data yet. Ask in chat or load the default R_100 chart.",
        "latest_tick": "Latest Tick",
        "live_results": "Live Results",
        "initial_message": "Hi. I can check Deriv markets, draw candlestick charts, or execute demo trades with your configured Deriv token.",
        "default_log": "Waiting for a trading command. This panel will show: data read -> condition check -> automatic order trigger.",
        "token_placeholder": "Paste a Deriv demo/live token",
        "token_help": "Stored only in the current Streamlit session. It is never hardcoded into source files.",
        "provider_help": "DeepSeek and other OpenAI-compatible providers are called through the OpenAI SDK base_url mode.",
        "local_rule_info": "Using the local rule parser. No model API key is required.",
        "compatible_key_placeholder": "Paste an OpenAI-compatible provider key",
        "api_key_help": "Stored only in the current Streamlit session. It is not written to source or config files.",
        "manual_model": "Enter another model name",
        "custom_model": "Custom model name",
        "base_url_help": "Use a base_url compatible with OpenAI Chat Completions.",
        "not_configured": "Not configured",
        "not_configured_or_not_needed": "Not configured / not required",
        "model_api": "Model API",
        "model_key": "Model Key",
        "model_name": "Model",
        "chart_note": "Mouse-wheel zoom, box zoom, drag pan, hover crosshair, line/rectangle/circle/free-path annotations, erase annotations, and PNG export are available from the chart toolbar.",
        "chart_height": "Chart Height",
        "compare_trend": "Overlay Comparison",
        "compare_symbol": "Comparison Symbol",
        "compare_placeholder": "Example: R_75 / frxEURUSD",
        "refresh_current": "Refresh Current Chart",
        "refresh_compare": "Load / Refresh Compare",
        "measure": "Measure",
        "start_candle": "Start Candle",
        "end_candle": "End Candle",
        "measure_hint": "Select two different candles to measure price and time distance.",
        "bar_count": "Candles",
        "time_span": "Time Span",
        "close_delta": "Close Delta",
        "range_amplitude": "Range",
        "measure_data": "Measurement, Range Analysis, and Full Data",
        "full_ohlcv": "Full OHLCV",
        "download_ohlcv": "Download OHLCV CSV",
        "download_log": "Download Execution Log",
        "success_badge": "Success badge · Deriv order receipt confirmed",
        "chart_empty_info": "No drawable candle data yet. Try: Draw the latest 60 one-minute candles for R_100.",
        "chart_title_suffix": "Candlestick Trading Chart",
        "local_provider_label": "Local Rules",
        "example_tick": "R_100 latest tick",
        "example_candles": "R_100 · 120 candles · 1m",
        "example_trade": "10 USD CALL · 5 ticks",
    },
}

MODEL_PRESETS: dict[Provider, list[str]] = {
    "本地规则": ["local-rule-engine"],
    "OpenAI": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
    "DeepSeek": ["deepseek-chat", "deepseek-reasoner"],
    "Anthropic": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"],
    "OpenAI-Compatible": ["custom-model"],
}

OPENAI_COMPATIBLE_BASE_URLS: dict[Provider, str | None] = {
    "OpenAI": None,
    "DeepSeek": "https://api.deepseek.com",
    "OpenAI-Compatible": None,
    "Anthropic": None,
    "本地规则": None,
}


@dataclass(slots=True)
class ToolPlan:
    action: Action
    params: dict[str, Any]
    rationale: str


@dataclass(slots=True)
class AgentEvent:
    speaker: str
    target: str
    message: str

    def line(self) -> str:
        return f"[{self.speaker} ➔ {self.target}]：{self.message}"


@dataclass(slots=True)
class TeamRunResult:
    final_answer: str
    events: list[AgentEvent]
    market_report: dict[str, Any] | None = None
    execution_report: dict[str, Any] | None = None
    ok: bool = True
    agent_reports: dict[str, Any] | None = None


AGENT_SPECS: dict[str, dict[str, str]] = {
    "manager": {
        "code": "PM",
        "zh_name": "交易经理",
        "en_name": "Trading Manager",
        "zh_role": "拆解目标，调度团队，汇总决策",
        "en_role": "Breaks goals into tasks, routes work, and summarizes decisions",
        "color": "#7dffcb",
    },
    "market": {
        "code": "MA",
        "zh_name": "行情分析师",
        "en_name": "Market Analyst",
        "zh_role": "读取 Tick/K 线，判断趋势与触发条件",
        "en_role": "Reads ticks/candles and validates trigger conditions",
        "color": "#00b894",
    },
    "strategy": {
        "code": "SA",
        "zh_name": "策略研究员",
        "en_name": "Strategy Researcher",
        "zh_role": "把目标拆成交易假设、观察窗口和入场计划",
        "en_role": "Turns goals into hypotheses, windows, and entry plans",
        "color": "#7aa7ff",
    },
    "risk": {
        "code": "RS",
        "zh_name": "风控官",
        "en_name": "Risk Sentinel",
        "zh_role": "检查账户、仓位、Token 和风险边界",
        "en_role": "Checks account, exposure, token state, and limits",
        "color": "#f5b84b",
    },
    "execution": {
        "code": "EX",
        "zh_name": "执行交易员",
        "en_name": "Execution Trader",
        "zh_role": "只在条件满足后提交 Deriv 模拟盘订单",
        "en_role": "Submits Deriv demo orders only after conditions pass",
        "color": "#ff7a7a",
    },
    "compliance": {
        "code": "CO",
        "zh_name": "合规审查员",
        "en_name": "Compliance Reviewer",
        "zh_role": "阻止含糊、高风险或未授权的资产操作",
        "en_role": "Blocks vague, high-risk, or unauthorized asset actions",
        "color": "#c39bff",
    },
    "chart": {
        "code": "CH",
        "zh_name": "图表工程师",
        "en_name": "Chart Engineer",
        "zh_role": "生成多图表快照、对比与可下载数据",
        "en_role": "Creates chart snapshots, comparisons, and downloadable data",
        "color": "#6ee7f9",
    },
    "report": {
        "code": "RP",
        "zh_name": "报告员",
        "en_name": "Report Agent",
        "zh_role": "整理时间线、回执和可审计复盘",
        "en_role": "Packages timelines, receipts, and audit summaries",
        "color": "#d8d257",
    },
}


def current_lang() -> str:
    return st.session_state.get("language", "zh")


def t(key: str) -> str:
    return I18N.get(current_lang(), I18N["zh"]).get(key, I18N["zh"].get(key, key))


def text_for(lang: str, key: str) -> str:
    return I18N.get(lang, I18N["zh"]).get(key, I18N["zh"].get(key, key))


def initial_message(lang: str | None = None) -> str:
    return text_for(lang or current_lang(), "initial_message")


def default_agent_log(lang: str | None = None) -> str:
    return text_for(lang or current_lang(), "default_log")


def provider_display(provider: Provider) -> str:
    if provider == "本地规则":
        return t("local_provider_label")
    return provider


def sync_language_defaults(previous_lang: str, next_lang: str) -> None:
    old_initials = {initial_message("zh"), initial_message("en")}
    if (
        not st.session_state.messages
        or (
            len(st.session_state.messages) == 1
            and st.session_state.messages[0].get("role") == "assistant"
            and st.session_state.messages[0].get("content") in old_initials
        )
    ):
        st.session_state.messages = [{"role": "assistant", "content": initial_message(next_lang)}]

    old_logs = {
        default_agent_log("zh"),
        default_agent_log("en"),
        "等待交易指令。这里会显示经理-员工协作和执行链。",
        "等待交易指令。这里会显示：数据读取 -> 条件判断 -> 自动触发下单 的完整执行链。",
    }
    if st.session_state.agent_execution_log in old_logs:
        st.session_state.agent_execution_log = default_agent_log(next_lang)
    st.session_state.last_language = next_lang


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def role_label(role: str) -> str:
    if current_lang() == "zh":
        return role
    return {
        "用户": "User",
        "经理": "Manager",
        "行情分析师": "Market Analyst",
        "风控执行员": "Risk Execution Agent",
        "执行交易员": "Execution Trader",
        "策略研究员": "Strategy Researcher",
        "风控官": "Risk Sentinel",
        "合规审查员": "Compliance Reviewer",
        "图表工程师": "Chart Engineer",
        "报告员": "Report Agent",
        "系统": "System",
    }.get(role, role)


def localize_event_message(event: AgentEvent) -> str:
    if current_lang() == "zh" or not has_cjk(event.message):
        return event.message
    if event.speaker == "用户":
        return event.message
    if event.speaker == "经理" and event.target == "行情分析师":
        return "Please check the requested market data and report the trigger condition."
    if event.speaker == "行情分析师" and event.target == "经理":
        tick = ((st.session_state.last_tick or {}).get("data") or {}).get("tick") or {}
        if tick:
            return f"Market check completed. Latest {tick.get('symbol', DEFAULT_SYMBOL)} quote: {tick.get('quote')}."
        return "Market check completed. I updated the latest market report."
    if event.speaker == "经理" and event.target in {"风控执行员", "执行交易员"}:
        return "Risk condition passed. Prepare the authorized demo order."
    if event.speaker == "经理" and event.target == "策略研究员":
        return "Break down this trading goal into a practical agent workflow."
    if event.speaker == "策略研究员" and event.target == "经理":
        return "Strategy plan ready: market read, risk check, compliance review, execution, then report."
    if event.speaker == "经理" and event.target == "风控官":
        return "Check account state, token status, and risk boundaries."
    if event.speaker == "风控官" and event.target == "经理":
        return "Risk check completed. Continue only if amount, token, and direction are valid."
    if event.speaker == "经理" and event.target == "合规审查员":
        return "Review the instruction for clarity, authorization, and excessive risk."
    if event.speaker == "合规审查员" and event.target == "经理":
        return "Compliance review completed. I flagged missing or risky fields when needed."
    if event.speaker == "经理" and event.target == "图表工程师":
        return "Create a fresh candle snapshot and make it available in the chart tabs."
    if event.speaker == "图表工程师" and event.target == "经理":
        return f"Chart snapshot completed. Available snapshots: {len(st.session_state.chart_snapshots)}."
    if event.speaker == "经理" and event.target == "报告员":
        return "Prepare the audit timeline and run recap."
    if event.speaker == "报告员" and event.target == "经理":
        return "Report ready: timeline, active agents, chart snapshots, and receipt state are summarized."
    if event.speaker in {"风控执行员", "执行交易员"} and event.target == "经理":
        if "无法执行" in event.message:
            return "Cannot execute: Deriv API token is not configured."
        if "下单成功" in event.message:
            contract_match = re.search(r"(?:合同ID|Contract ID)[:：]?\s*([^，, ]+)", event.message)
            price_match = re.search(r"(?:成交价|purchase price)[:：]?\s*([^，, ]+)", event.message)
            contract = contract_match.group(1) if contract_match else "received"
            price = price_match.group(1) if price_match else "confirmed"
            return f"Order submitted successfully. Contract ID: {contract}; purchase price: {price}."
        if "下单失败" in event.message:
            return "Order failed. Check the structured result for the exact Deriv error."
        return "Execution check completed. I updated the order report."
    if event.speaker == "经理" and event.target == "用户":
        return "The manager completed the coordinated run. Review the market report, order receipt, and execution log."
    if event.speaker == "系统":
        return "Model tool calling failed. Falling back to the local Python state machine."
    return event.message


def localized_event_line(event: AgentEvent) -> str:
    separator = "：" if current_lang() == "zh" else ": "
    return (
        f"[{role_label(event.speaker)} ➔ {role_label(event.target)}]"
        f"{separator}{localize_event_message(event)}"
    )


def agent_state_fallback(agent_id: str) -> str:
    if agent_id == "market":
        tick = ((st.session_state.last_tick or {}).get("data") or {}).get("tick") or {}
        if current_lang() == "en" and tick:
            return f"Market check completed. Latest {tick.get('symbol', DEFAULT_SYMBOL)} quote: {tick.get('quote')}."
        if current_lang() == "zh" and tick:
            return f"我刚查完 {tick.get('symbol', DEFAULT_SYMBOL)}，最新价是 {tick.get('quote')}。"
        return t("market_default_bubble")

    if agent_id == "strategy":
        return (
            "我会把老板目标拆成行情、风控、合规、执行和报告任务。"
            if current_lang() == "zh"
            else "I split the boss goal into market, risk, compliance, execution, and report tasks."
        )
    if agent_id == "risk":
        return (
            "我会先检查 Token、账户和金额边界，再允许进入执行。"
            if current_lang() == "zh"
            else "I check token, account state, and amount boundaries before execution."
        )
    if agent_id == "compliance":
        return (
            "我会拦住缺金额、缺方向、满仓这类不清晰或过激指令。"
            if current_lang() == "zh"
            else "I block unclear or excessive instructions such as missing amount/direction or all-in risk."
        )
    if agent_id == "chart":
        if st.session_state.chart_snapshots:
            return (
                f"我已经生成 {len(st.session_state.chart_snapshots)} 张图表快照，可在右侧切换。"
                if current_lang() == "zh"
                else f"I created {len(st.session_state.chart_snapshots)} chart snapshots. Switch them on the right."
            )
        return (
            "我负责生成多张 K 线快照、对比和 CSV 数据。"
            if current_lang() == "zh"
            else "I create multiple candle snapshots, comparisons, and CSV data."
        )
    if agent_id == "report":
        return (
            "我负责把每轮任务时间线和回执整理成可审计复盘。"
            if current_lang() == "zh"
            else "I package each run into an auditable timeline and recap."
        )

    receipt = ((st.session_state.last_trade_receipt or {}).get("data") or {}).get("receipt") or {}
    if current_lang() == "en" and receipt:
        return (
            "Order submitted successfully. "
            f"Contract ID: {receipt.get('contract_id')}; "
            f"purchase price: {receipt.get('purchase_price')} {receipt.get('currency', '')}."
        )
    if current_lang() == "zh" and receipt:
        return (
            "我刚提交了模拟盘订单。"
            f"合同 ID：{receipt.get('contract_id')}，成交价：{receipt.get('purchase_price')}。"
        )
    return t("execution_default_bubble")


def init_local_db() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS team_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                user_prompt TEXT NOT NULL,
                final_answer TEXT NOT NULL,
                ok INTEGER NOT NULL,
                events_json TEXT NOT NULL,
                market_report_json TEXT,
                execution_report_json TEXT,
                log_text TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                contract_id TEXT,
                symbol TEXT,
                contract_type TEXT,
                amount REAL,
                purchase_price REAL,
                currency TEXT,
                receipt_json TEXT NOT NULL
            )
            """
        )


def save_team_run(user_prompt: str, result: TeamRunResult) -> None:
    init_local_db()
    log_text = st.session_state.get("agent_execution_log", "")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO team_runs (
                created_at, user_prompt, final_answer, ok, events_json,
                market_report_json, execution_report_json, log_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                user_prompt,
                result.final_answer,
                1 if result.ok else 0,
                json.dumps([event.line() for event in result.events], ensure_ascii=False),
                json.dumps(result.market_report, ensure_ascii=False, default=str)
                if result.market_report
                else None,
                json.dumps(result.execution_report, ensure_ascii=False, default=str)
                if result.execution_report
                else None,
                log_text,
            ),
        )
        receipt = (result.execution_report or {}).get("receipt") or {}
        if receipt:
            conn.execute(
                """
                INSERT INTO trade_receipts (
                    created_at, contract_id, symbol, contract_type, amount,
                    purchase_price, currency, receipt_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    str(receipt.get("contract_id") or ""),
                    str(receipt.get("symbol") or ""),
                    str(receipt.get("contract_type") or ""),
                    float(receipt.get("purchase_price") or 0),
                    float(receipt.get("purchase_price") or 0),
                    str(receipt.get("currency") or ""),
                    json.dumps(receipt, ensure_ascii=False, default=str),
                ),
            )


def load_recent_runs(limit: int = 5) -> list[dict[str, Any]]:
    init_local_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, created_at, user_prompt, final_answer, ok
            FROM team_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


SYSTEM_PROMPT = """
你是 Deriv Smart Trading Gateway 的中文自动交易执行智能体。你的任务是把用户自然语言转换成严格 JSON，并优先支持交易执行闭环。
只能输出 JSON，不要输出 Markdown。

可用 action:
1. get_market_ticks: 获取最新 tick
   params: {"symbol": "R_100", "subscribe": false}
2. get_historical_candles: 获取 K 线
   params: {"symbol": "R_100", "granularity": 60, "count": 60}
3. execute_simulated_trade: 执行模拟交易
   params: {
     "symbol": "R_100",
     "amount": 10.0,
     "contract_type": "CALL",
     "duration": 5,
     "duration_unit": "m",
     "condition": null,
     "market_read": "tick",
     "auto_execute": true
   }
4. chat: 普通解释或澄清
   params: {}

Deriv symbol 示例:
- R_100 表示 Volatility 100 Index
- R_75 表示 Volatility 75 Index
- frxEURUSD 表示 EUR/USD

中文映射:
- K线、蜡烛图、历史走势、1分钟K、5分钟K、1小时K -> get_historical_candles
- 最新价、行情、报价、tick -> get_market_ticks
- 购买、下单、建仓、开仓、买入、买涨、做多、看涨、上涨、CALL -> execute_simulated_trade contract_type CALL
- 买跌、做空、看跌、下跌、PUT -> execute_simulated_trade contract_type PUT
- 平仓：当前只允许通过 execute_simulated_trade 提交新的模拟合约，不能真正 sell/close 现有合约；如果用户没有说明方向，action=chat 要求补充 CALL 或 PUT。
- 1分钟=60, 5分钟=300, 1小时=3600
- 如果用户说“如果/当/高于/低于/突破/跌破/大于/小于 ... 就下单”，必须把条件写入 condition:
  {"metric": "latest_tick", "operator": ">", "value": 350.0}
- 条件支持 latest_tick 的 >, >=, <, <=。条件下单也必须 action=execute_simulated_trade，后台会先读取行情再判断，再自动触发下单。

交易执行要求:
- 用户出现“购买/下单/建仓/开仓/买入/平仓/做多/做空/买涨/买跌”等写操作意图时，必须优先尝试输出 execute_simulated_trade。
- 如果缺少 symbol，默认 R_100。
- 如果缺少 duration_unit，默认 m。
- 如果用户有交易意图但缺少 duration，经理默认使用 duration=5, duration_unit=t，并在总结里说明。
- 如果缺少 amount、contract_type，action=chat 并说明缺哪个字段。
- 不要把交易意图降级成 get_market_ticks。
返回格式:
{
  "action": "execute_simulated_trade",
  "params": {
    "symbol": "R_100",
    "amount": 10.0,
    "contract_type": "CALL",
    "duration": 5,
    "duration_unit": "m",
    "condition": {"metric": "latest_tick", "operator": ">", "value": 350.0},
    "market_read": "tick",
    "auto_execute": true
  },
  "rationale": "用户要求条件满足后自动买涨"
}
""".strip()

MANAGER_SYSTEM_PROMPT = """
你是【交易经理 Trading Manager】，一个精通风控和团队调配的资深交易经理。
你直接对接人类用户，但你绝不能直接调用 Deriv 底层 API。你只能通过管理工具派活：

1. assign_task_to_market_agent
   派给【行情分析师】。用于抓取 tick/K线、判断趋势、检查连续下跌/上涨等市场条件。

2. assign_task_to_execution_agent
   派给【风控执行员】。用于检查账户、执行模拟盘订单、返回订单回执。
3. assign_task_to_strategy_agent
   派给【策略研究员】。用于拆解交易目标、提出观察窗口、定义任务链。
4. assign_task_to_risk_agent
   派给【风控官】。用于检查账户、Token 和金额边界。
5. assign_task_to_compliance_agent
   派给【合规审查员】。用于阻止含糊、高风险或未授权操作。
6. assign_task_to_chart_agent
   派给【图表工程师】。用于生成 K 线快照、多图表和数据导出。
7. assign_task_to_report_agent
   派给【报告员】。用于整理本轮时间线和复盘摘要。

工作原则：
- 用户有交易、购买、下单、建仓、开仓、平仓、买涨、买跌、做多、做空等意图时，必须先派行情分析师读取必要行情，再根据结果决定是否派执行员。
- 对复杂目标，先派策略研究员拆解，再派行情、风控、合规、执行、报告。
- 如果用户给出条件，例如“连续三个 Tick 都在跌”“高于 350 再买”，先派行情分析师验证条件。
- 如果条件满足且交易参数完整，先派风控官和合规审查员，再派执行交易员执行模拟盘订单。
- 如果缺少 amount、contract_type、duration 等关键字段，要向用户说明缺什么。
- 你需要最终用简明中文总结：经理如何拆解任务、员工反馈、是否执行交易、订单结果。
- 不要输出隐藏推理，只输出可审计的行动摘要。
""".strip()

MANAGER_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "assign_task_to_market_agent",
            "description": "派行情分析师读取 Deriv 行情数据并返回趋势/条件判断报告。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "经理给行情分析师的中文任务说明。"},
                    "symbol": {"type": "string", "description": "Deriv symbol，例如 R_100。"},
                    "tick_count": {"type": "integer", "minimum": 3, "maximum": 30, "default": 10},
                    "granularity": {"type": "integer", "enum": [60, 300, 3600], "default": 60},
                    "candle_count": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 60},
                    "analysis_goal": {
                        "type": "string",
                        "description": "tick_trend / candle_trend / consecutive_down / consecutive_up / latest_price。",
                    },
                },
                "required": ["task", "symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_task_to_execution_agent",
            "description": "派风控执行员检查账户并执行 Deriv 模拟盘订单。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "经理给执行员的中文任务说明。"},
                    "symbol": {"type": "string", "description": "Deriv symbol，例如 R_100。"},
                    "amount": {"type": "number", "exclusiveMinimum": 0},
                    "contract_type": {"type": "string", "enum": ["CALL", "PUT"]},
                    "duration": {"type": "integer", "minimum": 1},
                    "duration_unit": {"type": "string", "enum": ["m", "h", "t"]},
                    "risk_note": {"type": "string", "description": "经理给执行员的风控边界。"},
                },
                "required": ["task", "symbol", "amount", "contract_type", "duration", "duration_unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_task_to_strategy_agent",
            "description": "派策略研究员拆解用户目标，形成交易假设、观察窗口和任务链。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "symbol": {"type": "string"},
                },
                "required": ["task", "symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_task_to_risk_agent",
            "description": "派风控官检查账户、Token、金额和风险边界。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "symbol": {"type": "string"},
                    "amount": {"type": "number", "default": 0},
                },
                "required": ["task", "symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_task_to_compliance_agent",
            "description": "派合规审查员检查指令是否含糊、高风险或缺少授权参数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "amount": {"type": "number", "default": 0},
                    "contract_type": {"type": "string", "enum": ["CALL", "PUT", ""], "default": ""},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_task_to_chart_agent",
            "description": "派图表工程师生成 K 线图表快照，支持多快照切换。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "symbol": {"type": "string"},
                    "granularity": {"type": "integer", "enum": [60, 300, 3600], "default": 60},
                    "count": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 120},
                },
                "required": ["task", "symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_task_to_report_agent",
            "description": "派报告员整理团队时间线、关键回执和本地可审计摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                },
                "required": ["task"],
            },
        },
    },
]


def init_state() -> None:
    defaults = {
        "deriv_token": "",
        "llm_provider": "本地规则",
        "llm_api_key": "",
        "llm_model": "local-rule-engine",
        "custom_base_url": "",
        "provider": "本地规则",
        "language": "zh",
        "last_language": "zh",
        "messages": [{"role": "assistant", "content": text_for("zh", "initial_message")}],
        "last_candles": None,
        "last_trade_receipt": None,
        "last_tick": None,
        "last_plan": None,
        "prompt_nonce": 0,
        "chart_height": 620,
        "compare_symbol": "R_75",
        "compare_result": None,
        "agent_execution_log": text_for("zh", "default_log"),
        "team_events": [],
        "agent_reports": {},
        "runtime_events": [],
        "api_trace": [],
        "sync_version": 0,
        "chart_snapshots": [],
        "direct_prompt_nonce": 0,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    # Backward-compatible migration from the previous separate-key UI.
    if not st.session_state.llm_api_key:
        legacy_provider = st.session_state.get("provider", "本地规则")
        if legacy_provider == "OpenAI" and st.session_state.get("openai_key"):
            st.session_state.llm_provider = "OpenAI"
            st.session_state.llm_api_key = st.session_state.openai_key
            st.session_state.llm_model = st.session_state.get("openai_model", "gpt-4o-mini")
        elif legacy_provider == "Anthropic" and st.session_state.get("anthropic_key"):
            st.session_state.llm_provider = "Anthropic"
            st.session_state.llm_api_key = st.session_state.anthropic_key
            st.session_state.llm_model = st.session_state.get(
                "anthropic_model", "claude-3-5-sonnet-latest"
            )


def configure_page() -> None:
    st.set_page_config(
        page_title="Deriv Smart Trading Gateway",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        :root {
            --bg: #08110f;
            --panel: #101a17;
            --panel-2: #13231f;
            --line: #263b34;
            --text: #e8f2ed;
            --muted: #91a49b;
            --soft: #c6d7cf;
            --green: #00b894;
            --green-2: #7dffcb;
            --red: #ff5d5d;
            --amber: #f5b84b;
            --blue: #7aa7ff;
        }
        .stApp {
            background:
                linear-gradient(90deg, rgba(0,184,148,.055) 1px, transparent 1px),
                linear-gradient(0deg, rgba(122,167,255,.04) 1px, transparent 1px),
                radial-gradient(circle at 78% -10%, rgba(0,184,148,.18), transparent 34%),
                var(--bg);
            background-size: 44px 44px, 44px 44px, auto;
            color: var(--text);
        }
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        [data-testid="stMainBlockContainer"],
        .block-container {
            color: var(--text) !important;
        }
        [data-testid="stMain"] h1,
        [data-testid="stMain"] h2,
        [data-testid="stMain"] h3,
        [data-testid="stMain"] p,
        [data-testid="stMain"] span,
        [data-testid="stMain"] label,
        [data-testid="stMain"] div {
            color: var(--text);
        }
        .block-container {
            padding-top: 1.25rem;
            padding-bottom: 2rem;
            max-width: 1500px;
        }
        [data-testid="stSidebar"] {
            background: #06100d;
            border-right: 1px solid var(--line);
        }
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span {
            color: var(--soft) !important;
        }
        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] textarea,
        [data-testid="stSidebar"] select {
            color: var(--text) !important;
        }
        .terminal-hero {
            border: 1px solid var(--line);
            background: linear-gradient(135deg, rgba(16,26,23,.98), rgba(19,35,31,.94));
            padding: 1.05rem 1.15rem;
            margin-bottom: 1rem;
            box-shadow: 0 22px 70px rgba(0,0,0,.25);
        }
        .terminal-hero-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 1rem;
        }
        .terminal-kicker {
            color: var(--green-2) !important;
            font-size: .74rem;
            letter-spacing: .12em;
            text-transform: uppercase;
            font-weight: 900;
            margin-bottom: .25rem;
        }
        .terminal-title {
            font-size: 2rem;
            font-weight: 900;
            line-height: 1.05;
            color: var(--text) !important;
            margin: 0;
        }
        .terminal-subtitle {
            color: var(--muted) !important;
            margin-top: .4rem;
            max-width: 780px;
        }
        .live-chip {
            border: 1px solid rgba(0,184,148,.45);
            background: rgba(0,184,148,.12);
            color: var(--green-2) !important;
            padding: .4rem .6rem;
            font-size: .78rem;
            font-weight: 900;
            white-space: nowrap;
        }
        .agent-stage {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
            gap: .75rem;
            margin: .6rem 0 1rem;
        }
        .agent-card {
            border: 1px solid var(--line);
            background: linear-gradient(180deg, rgba(19,35,31,.96), rgba(9,18,16,.98));
            padding: .9rem;
            min-height: 150px;
            box-shadow: 0 18px 50px rgba(0,0,0,.22);
        }
        .agent-head {
            display: flex;
            align-items: center;
            gap: .7rem;
            margin-bottom: .7rem;
        }
        .agent-icon {
            width: 42px;
            height: 42px;
            display: grid;
            place-items: center;
            border: 1px solid rgba(0,184,148,.46);
            background: rgba(0,184,148,.12);
            color: var(--green-2) !important;
            font-weight: 950;
            animation: agentPulse 1.9s ease-in-out infinite;
        }
        .agent-icon.exec {
            border-color: rgba(245,184,75,.55);
            background: rgba(245,184,75,.12);
            color: #ffd886 !important;
        }
        @keyframes agentPulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(0,184,148,.3); }
            50% { box-shadow: 0 0 0 8px rgba(0,184,148,0); }
        }
        .agent-name {
            font-weight: 900;
            color: var(--text) !important;
        }
        .agent-role {
            color: var(--muted) !important;
            font-size: .8rem;
        }
        .agent-status-row {
            display: flex;
            align-items: center;
            gap: .5rem;
            color: var(--muted) !important;
            font-size: .76rem;
            font-weight: 800;
            margin-bottom: .55rem;
        }
        .agent-chip {
            border: 1px solid rgba(0,184,148,.42);
            background: rgba(0,184,148,.12);
            color: var(--green-2) !important;
            padding: .18rem .42rem;
            text-transform: uppercase;
        }
        .agent-chip.exec {
            border-color: rgba(245,184,75,.45);
            background: rgba(245,184,75,.12);
            color: #ffd886 !important;
        }
        .agent-bubble {
            border: 1px solid rgba(145,164,155,.25);
            background: rgba(255,255,255,.045);
            color: var(--soft) !important;
            padding: .65rem .7rem;
            font-size: .86rem;
            line-height: 1.45;
        }
        .agent-bubble strong {
            color: var(--green-2) !important;
        }
        [data-testid="stVerticalBlockBorderWrapper"],
        [data-testid="stChatMessage"] {
            border-color: var(--line) !important;
            background: rgba(16,26,23,.92) !important;
            box-shadow: 0 20px 60px rgba(0,0,0,.22);
        }
        [data-testid="stChatMessage"] p,
        [data-testid="stChatMessage"] span,
        [data-testid="stChatMessage"] div {
            color: var(--text) !important;
        }
        .success-badge {
            border: 1px solid rgba(0,184,148,.45);
            background: rgba(0,184,148,.12);
            color: var(--green-2) !important;
            padding: .85rem 1rem;
            font-weight: 900;
            font-size: 1rem;
        }
        .small-muted {
            color: var(--muted) !important;
            font-size: .86rem;
        }
        .command-panel {
            border: 1px solid var(--line);
            background: linear-gradient(180deg, rgba(19,35,31,.98), rgba(12,22,19,.98));
            padding: 1rem;
            margin: .55rem 0 1rem;
            box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
        }
        .command-title {
            color: var(--text) !important;
            font-size: 1rem;
            font-weight: 900;
            margin-bottom: .25rem;
        }
        .command-hint {
            color: var(--muted) !important;
            font-size: .86rem;
            line-height: 1.5;
            margin-bottom: .8rem;
        }
        .example-strip {
            display: flex;
            flex-wrap: wrap;
            gap: .45rem;
            margin: .2rem 0 .9rem;
        }
        .example-pill {
            border: 1px solid rgba(0,184,148,.26);
            background: rgba(0,184,148,.08);
            color: var(--soft) !important;
            padding: .28rem .55rem;
            font-size: .78rem;
            font-weight: 700;
        }
        .send-note {
            color: var(--muted) !important;
            font-size: .82rem;
            padding-top: .45rem;
        }
        div[data-testid="stTextArea"] textarea {
            border: 1px solid var(--line);
            background: #08110f;
            color: var(--text) !important;
            min-height: 104px;
            line-height: 1.55;
            font-size: .98rem;
        }
        div[data-testid="stTextArea"] textarea::placeholder {
            color: var(--muted) !important;
            opacity: 1;
        }
        div[data-testid="stTextArea"] textarea:focus {
            border-color: var(--green);
            box-shadow: 0 0 0 3px rgba(0,184,148,.16);
        }
        .stButton > button {
            border-radius: 0;
            border: 1px solid var(--line);
            background: #13231f;
            color: var(--text);
            font-weight: 900;
        }
        .stButton > button[kind="primary"] {
            background: var(--green);
            border-color: var(--green);
            color: #ffffff;
        }
        .chart-workbench {
            border: 1px solid var(--line);
            background: linear-gradient(180deg, #111c18, #0a1411);
            color: var(--text);
            padding: 1rem;
            box-shadow: 0 22px 70px rgba(0,0,0,.28);
            margin-bottom: 1rem;
        }
        .chart-workbench strong,
        .chart-workbench span,
        .chart-workbench p,
        .chart-workbench div {
            color: var(--text) !important;
        }
        .chart-toolbar-note {
            color: var(--muted) !important;
            font-size: .84rem;
            line-height: 1.5;
            margin-top: .25rem;
        }
        .chart-stat {
            border: 1px solid var(--line);
            background: rgba(16,26,23,.92);
            padding: .75rem .85rem;
            min-height: 78px;
        }
        .chart-stat span {
            display: block;
            color: var(--muted) !important;
            font-size: .78rem;
            font-weight: 800;
            text-transform: uppercase;
        }
        .chart-stat strong {
            display: block;
            color: var(--text) !important;
            font-size: 1.35rem;
            margin-top: .2rem;
        }
        [data-testid="stCodeBlock"] pre {
            background: #050b09 !important;
            border: 1px solid var(--line);
            color: var(--green-2) !important;
        }
        div[data-baseweb="select"] * {
            color: var(--text) !important;
        }
        input {
            color: var(--text) !important;
        }
        @media (max-width: 900px) {
            .terminal-hero-top,
            .agent-stage {
                grid-template-columns: 1fr;
                display: grid;
            }
            .terminal-title {
                font-size: 1.55rem;
            }
            .block-container {
                padding-left: .85rem;
                padding-right: .85rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> None:
    with st.sidebar:
        st.title(t("sidebar_title"))
        st.caption(t("sidebar_caption"))

        language = st.selectbox(
            t("language"),
            ["zh", "en"],
            index=["zh", "en"].index(st.session_state.language),
            format_func=lambda value: "中文" if value == "zh" else "English",
        )
        previous_language = st.session_state.get("last_language", st.session_state.language)
        st.session_state.language = language
        sync_language_defaults(previous_language, language)

        st.subheader(t("security"))
        deriv_token = st.text_input(
            t("deriv_token"),
            value=st.session_state.deriv_token,
            type="password",
            placeholder=t("token_placeholder"),
            help=t("token_help"),
        )

        provider_options: list[Provider] = [
            "本地规则",
            "OpenAI",
            "DeepSeek",
            "Anthropic",
            "OpenAI-Compatible",
        ]
        current_provider = st.session_state.llm_provider
        if current_provider not in provider_options:
            current_provider = "本地规则"

        selected_provider = st.selectbox(
            t("llm_api"),
            provider_options,
            index=provider_options.index(current_provider),
            format_func=provider_display,
            help=t("provider_help"),
        )
        st.session_state.llm_provider = selected_provider

        st.session_state.deriv_token = deriv_token

        if selected_provider == "本地规则":
            st.session_state.llm_api_key = ""
            st.session_state.llm_model = "local-rule-engine"
            st.info(t("local_rule_info"))
        else:
            placeholder = {
                "OpenAI": "sk-...",
                "DeepSeek": "sk-...",
                "Anthropic": "sk-ant-...",
                "OpenAI-Compatible": t("compatible_key_placeholder"),
            }[selected_provider]
            st.session_state.llm_api_key = st.text_input(
                f"{selected_provider} API Key",
                value=st.session_state.llm_api_key,
                type="password",
                placeholder=placeholder,
                help=t("api_key_help"),
            )

            model_options = MODEL_PRESETS[selected_provider]
            current_model = st.session_state.llm_model
            if current_model not in model_options:
                current_model = model_options[0]
            chosen_model = st.selectbox(
                t("model"),
                model_options + [t("manual_model")],
                index=model_options.index(current_model) if current_model in model_options else 0,
            )
            if chosen_model == t("manual_model"):
                st.session_state.llm_model = st.text_input(
                    t("custom_model"),
                    value="" if current_model in model_options else current_model,
                    placeholder="qwen-plus / llama-3.1-70b / vendor-model",
                )
            else:
                st.session_state.llm_model = chosen_model

            if selected_provider == "OpenAI-Compatible":
                st.session_state.custom_base_url = st.text_input(
                    "Base URL",
                    value=st.session_state.custom_base_url,
                    placeholder="https://api.your-provider.com/v1",
                    help=t("base_url_help"),
                )
            elif selected_provider == "DeepSeek":
                st.caption("DeepSeek base_url: https://api.deepseek.com")

        st.divider()
        st.subheader(t("connection"))
        st.write(f"Deriv Token: `{mask_secret(deriv_token) if deriv_token else t('not_configured')}`")
        st.write(f"{t('model_api')}: `{provider_display(selected_provider)}`")
        st.write(
            f"{t('model_key')}: `{mask_secret(st.session_state.llm_api_key) if st.session_state.llm_api_key else t('not_configured_or_not_needed')}`"
        )
        st.write(f"{t('model_name')}: `{st.session_state.llm_model}`")
        st.caption(f"{t('db_path')}: `{DB_PATH}`")

        st.divider()
        st.subheader(t("history"))
        for row in load_recent_runs(5):
            status = "OK" if row["ok"] else "BLOCKED"
            with st.expander(f"#{row['id']} · {status} · {row['created_at'][:16]}", expanded=False):
                st.caption(row["user_prompt"])
                st.write(row["final_answer"])

        if st.button(t("clear_chat"), width="stretch"):
            st.session_state.messages = []
            st.session_state.last_candles = None
            st.session_state.last_trade_receipt = None
            st.session_state.last_tick = None
            st.session_state.last_plan = None
            st.session_state.prompt_nonce += 1
            st.session_state.team_events = []
            st.session_state.runtime_events = []
            st.session_state.api_trace = []
            st.session_state.sync_version = 0
            st.session_state.agent_reports = {}
            st.session_state.chart_snapshots = []
            st.session_state.agent_execution_log = default_agent_log()
            st.session_state.messages = [{"role": "assistant", "content": initial_message()}]
            st.rerun()


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


def make_plan(user_text: str) -> ToolPlan:
    provider: Provider = st.session_state.llm_provider
    if provider in {"OpenAI", "DeepSeek", "OpenAI-Compatible"} and st.session_state.llm_api_key:
        planned = plan_with_openai_compatible(user_text, provider)
        if planned:
            return planned
    if provider == "Anthropic" and st.session_state.llm_api_key:
        planned = plan_with_anthropic(user_text)
        if planned:
            return planned
    return local_rule_plan(user_text)


def plan_with_openai_compatible(user_text: str, provider: Provider) -> ToolPlan | None:
    try:
        from openai import OpenAI

        base_url = OPENAI_COMPATIBLE_BASE_URLS.get(provider)
        if provider == "OpenAI-Compatible":
            base_url = st.session_state.custom_base_url.strip() or None
            if not base_url:
                st.warning(
                    "请先填写 OpenAI-Compatible 的 Base URL，已切换本地规则。"
                    if current_lang() == "zh"
                    else "Please enter an OpenAI-Compatible Base URL. Falling back to local rules."
                )
                return None

        client_kwargs = {"api_key": st.session_state.llm_api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = OpenAI(**client_kwargs)

        request: dict[str, Any] = {
            "model": st.session_state.llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.1,
        }
        if provider in {"OpenAI", "DeepSeek"}:
            request["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**request)
        content = response.choices[0].message.content or ""
        data = extract_json_object(content)
        return normalize_plan(data) if data else None
    except Exception as exc:
        if current_lang() == "zh":
            st.warning(f"{provider} 规划失败，已切换本地规则：{exc}")
        else:
            st.warning(f"{provider} planning failed. Falling back to local rules: {exc}")
        return None


def plan_with_anthropic(user_text: str) -> ToolPlan | None:
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=st.session_state.llm_api_key)
        response = client.messages.create(
            model=st.session_state.llm_model,
            max_tokens=700,
            temperature=0.1,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_text}],
        )
        content = "\n".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        data = extract_json_object(content)
        return normalize_plan(data) if data else None
    except Exception as exc:
        if current_lang() == "zh":
            st.warning(f"Anthropic 规划失败，已切换本地规则：{exc}")
        else:
            st.warning(f"Anthropic planning failed. Falling back to local rules: {exc}")
        return None


def normalize_plan(data: dict[str, Any]) -> ToolPlan:
    action = data.get("action", "chat")
    if action not in {
        "get_market_ticks",
        "get_historical_candles",
        "execute_simulated_trade",
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
    elif action == "execute_simulated_trade":
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
        if amount <= 0:
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
            action="execute_simulated_trade",
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
    lowered = text.lower()
    if any(word in text for word in ["买跌", "看跌", "做空", "下跌"]) or "put" in lowered:
        return "PUT"
    if any(word in text for word in ["买涨", "看涨", "做多", "上涨", "购买", "买入", "下单", "建仓", "开仓", "平仓"]) or "call" in lowered:
        return "CALL"
    return ""


def extract_symbol(text: str) -> str:
    symbol_match = re.search(r"\b(?:R_\d+|frx[A-Za-z]{6})\b", text, flags=re.IGNORECASE)
    if symbol_match:
        raw = symbol_match.group(0)
        return raw.upper() if raw.upper().startswith("R_") else raw[:3].lower() + raw[3:].upper()
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


def run_async(coro: Any) -> Any:
    return asyncio.run(coro)


def parse_tool_response(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": {"message": raw}}


def append_team_event(
    events: list[AgentEvent],
    speaker: str,
    target: str,
    message: str,
    writer: Callable[[str], None] | None = None,
) -> None:
    event = AgentEvent(speaker=speaker, target=target, message=message)
    events.append(event)
    localized = localized_event_line(event)
    st.session_state.team_events = (st.session_state.get("team_events", []) + [localized])[-80:]
    push_runtime_event("agent", role_label(speaker), role_label(target), localize_event_message(event))
    if writer:
        writer(localized)


def push_runtime_event(
    kind: str,
    source: str,
    target: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    event = {
        "time": datetime.now(LOCAL_TZ).strftime("%H:%M:%S.%f")[:-3],
        "kind": kind,
        "source": source,
        "target": target,
        "message": message,
        "payload": payload or {},
    }
    st.session_state.runtime_events = (st.session_state.runtime_events + [event])[-120:]
    st.session_state.sync_version = int(st.session_state.get("sync_version", 0)) + 1


def format_runtime_events(limit: int = 30) -> str:
    events = st.session_state.get("runtime_events", [])[-limit:]
    if not events:
        return default_agent_log()
    return "\n".join(
        f"{item['time']} [{item['kind']}] {item['source']} -> {item['target']}: {item['message']}"
        for item in events
    )


def record_api_trace(
    tool: str,
    status: str,
    params: dict[str, Any],
    result: dict[str, Any] | None = None,
    elapsed_ms: float | None = None,
) -> None:
    safe_params = {
        key: ("***" if "token" in key.lower() else value)
        for key, value in params.items()
    }
    trace = {
        "time": datetime.now(LOCAL_TZ).strftime("%H:%M:%S.%f")[:-3],
        "tool": tool,
        "status": status,
        "params": safe_params,
        "elapsed_ms": round(elapsed_ms, 1) if elapsed_ms is not None else None,
        "ok": None if result is None else bool(result.get("ok")),
        "summary": summarize_api_result(result) if result else "",
    }
    st.session_state.api_trace = (st.session_state.api_trace + [trace])[-80:]
    push_runtime_event("api", tool, "state", status, trace)


def summarize_api_result(result: dict[str, Any] | None) -> str:
    if not result:
        return ""
    if not result.get("ok"):
        return (result.get("error") or {}).get("message", "failed")
    data = result.get("data") or {}
    if data.get("tick"):
        tick = data["tick"]
        return f"{tick.get('symbol')} quote={tick.get('quote')}"
    if data.get("ohlcv"):
        return f"{data.get('symbol')} candles={data.get('returned_count')}"
    if data.get("receipt"):
        receipt = data["receipt"]
        return f"contract_id={receipt.get('contract_id')}"
    if data.get("balance") or data.get("portfolio"):
        return "account status loaded"
    return "ok"


def call_deriv_tool(
    tool_name: str,
    coro: Any,
    params: dict[str, Any],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    record_api_trace(tool_name, "START", params)
    started = time.perf_counter()
    try:
        result = parse_tool_response(run_async(coro))
    except Exception as exc:
        result = {"ok": False, "error": {"message": str(exc)}}
    elapsed = (time.perf_counter() - started) * 1000
    record_api_trace(tool_name, "DONE" if result.get("ok") else "FAILED", params, result, elapsed)
    if writer:
        writer(
            f"API {tool_name} -> {'OK' if result.get('ok') else 'FAILED'} "
            f"({elapsed:.0f}ms) {summarize_api_result(result)}"
        )
    return result


def publish_team_log(events: list[AgentEvent], extra_lines: list[str] | None = None) -> None:
    lines = [
        "Hierarchical Multi-Agent Trading Run",
        f"timestamp: {datetime.now(timezone.utc).isoformat()}",
        "-" * 72,
    ]
    lines.extend(localized_event_line(event) for event in events)
    if extra_lines:
        lines.append("-" * 72)
        lines.extend(extra_lines)
    st.session_state.agent_execution_log = "\n".join(lines)
    st.session_state.team_events = [localized_event_line(event) for event in events]


def agent_name(agent_id: str) -> str:
    spec = AGENT_SPECS[agent_id]
    return spec["zh_name"] if current_lang() == "zh" else spec["en_name"]


def agent_role(agent_id: str) -> str:
    spec = AGENT_SPECS[agent_id]
    return spec["zh_role"] if current_lang() == "zh" else spec["en_role"]


def remember_agent_report(agent_id: str, report: dict[str, Any]) -> None:
    st.session_state.agent_reports[agent_id] = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "report": report,
    }
    push_runtime_event(
        "agent_state",
        agent_name(agent_id),
        "Graph",
        "report synced",
        {"agent_id": agent_id, "ok": report.get("ok", True)},
    )


def add_chart_snapshot(result: dict[str, Any], source: str = "agent") -> None:
    if not result or not result.get("ok"):
        return
    data = result.get("data") or {}
    snapshot = {
        "id": f"{data.get('symbol', DEFAULT_SYMBOL)}-{datetime.now(timezone.utc).strftime('%H%M%S')}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "symbol": data.get("symbol", DEFAULT_SYMBOL),
        "granularity": data.get("granularity", DEFAULT_GRANULARITY),
        "count": data.get("returned_count", DEFAULT_COUNT),
        "result": result,
    }
    snapshots = [snapshot]
    for item in st.session_state.chart_snapshots:
        if len(snapshots) >= 6:
            break
        if item.get("id") != snapshot["id"]:
            snapshots.append(item)
    st.session_state.chart_snapshots = snapshots
    st.session_state.last_candles = result
    push_runtime_event(
        "chart",
        source,
        "Chart Snapshots",
        f"{snapshot['symbol']} snapshot synced",
        {"snapshot_id": snapshot["id"], "count": snapshot["count"]},
    )


def collect_market_ticks(
    symbol: str,
    count: int,
    writer: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    ticks: list[dict[str, Any]] = []
    first = call_deriv_tool(
        "get_market_ticks",
        get_market_ticks(symbol, True),
        {"symbol": symbol, "subscribe": True},
        writer,
    )
    if first.get("ok"):
        data = first.get("data") or {}
        if data.get("tick"):
            ticks.append(data["tick"])
        ticks.extend(data.get("stream_sample") or [])
        st.session_state.last_tick = first

    attempts = 0
    while len(ticks) < count and attempts < max(count, 3):
        attempts += 1
        time.sleep(0.12)
        item = call_deriv_tool(
            "get_market_ticks",
            get_market_ticks(symbol, False),
            {"symbol": symbol, "subscribe": False, "attempt": attempts},
            writer,
        )
        if item.get("ok"):
            tick = ((item.get("data") or {}).get("tick") or {})
            if tick:
                ticks.append(tick)
                st.session_state.last_tick = item

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for tick in ticks:
        key = (tick.get("epoch"), tick.get("quote"))
        if key not in seen:
            deduped.append(tick)
            seen.add(key)
    result = deduped[-count:]
    push_runtime_event(
        "table",
        "Market Analyst",
        "Tick Buffer",
        f"{symbol} ticks synced: {len(result)}",
        {"symbol": symbol, "count": len(result)},
    )
    return result


def analyze_tick_sequence(ticks: list[dict[str, Any]]) -> dict[str, Any]:
    quotes = [float(tick["quote"]) for tick in ticks if tick.get("quote") is not None]
    last_three = quotes[-3:]
    consecutive_three_down = len(last_three) == 3 and last_three[0] > last_three[1] > last_three[2]
    consecutive_three_up = len(last_three) == 3 and last_three[0] < last_three[1] < last_three[2]
    net_change = quotes[-1] - quotes[0] if len(quotes) >= 2 else 0.0
    trend = "flat"
    if consecutive_three_down or net_change < 0:
        trend = "down"
    if consecutive_three_up or net_change > 0:
        trend = "up"
    return {
        "quotes": quotes,
        "last_three": last_three,
        "latest_quote": quotes[-1] if quotes else None,
        "consecutive_three_down": consecutive_three_down,
        "consecutive_three_up": consecutive_three_up,
        "net_change": net_change,
        "trend": trend,
    }


def market_analyst_agent(
    *,
    task: str,
    symbol: str,
    tick_count: int = 10,
    granularity: int = 60,
    candle_count: int = 60,
    analysis_goal: str = "tick_trend",
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    append_team_event(
        events,
        "经理",
        "行情分析师",
        f"请处理：{task}；symbol={symbol}，tick_count={tick_count}，goal={analysis_goal}",
        writer,
    )
    ticks = collect_market_ticks(symbol, max(3, min(int(tick_count), 30)), writer)
    tick_analysis = analyze_tick_sequence(ticks)

    candle_result: dict[str, Any] | None = None
    if any(keyword in f"{task} {analysis_goal}" for keyword in ["K", "k", "蜡烛", "走势", "candle"]):
        candle_result = call_deriv_tool(
            "get_historical_candles",
            get_historical_candles(symbol, int(granularity), int(candle_count)),
            {"symbol": symbol, "granularity": int(granularity), "count": int(candle_count)},
            writer,
        )
        if candle_result.get("ok"):
            add_chart_snapshot(candle_result, source="market_agent")

    report = {
        "role": "Market Analyst Agent",
        "symbol": symbol,
        "task": task,
        "analysis_goal": analysis_goal,
        "tick_count": len(ticks),
        "tick_analysis": tick_analysis,
        "candles_loaded": bool(candle_result and candle_result.get("ok")),
        "candle_count": ((candle_result or {}).get("data") or {}).get("returned_count"),
    }
    if tick_analysis["consecutive_three_down"]:
        summary = (
            f"报告经理，{symbol} 最后三个 Tick 为 {tick_analysis['last_three']}，确认连续下跌。"
        )
    elif tick_analysis["consecutive_three_up"]:
        summary = (
            f"报告经理，{symbol} 最后三个 Tick 为 {tick_analysis['last_three']}，确认连续上涨。"
        )
    else:
        summary = (
            f"报告经理，{symbol} 最新价 {tick_analysis['latest_quote']}，"
            f"最近 Tick 未满足连续三根同向条件。"
        )
    report["summary"] = summary
    append_team_event(events, "行情分析师", "经理", summary, writer)
    remember_agent_report("market", report)
    return report


def strategy_agent(
    *,
    task: str,
    symbol: str,
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    append_team_event(events, "经理", "策略研究员", f"请拆解交易目标：{task}；symbol={symbol}", writer)
    market = st.session_state.agent_reports.get("market", {}).get("report", {})
    tick_analysis = market.get("tick_analysis") or {}
    trend = tick_analysis.get("trend", "unknown")
    plan = {
        "role": "Strategy Researcher",
        "symbol": symbol,
        "task": task,
        "hypothesis": f"{symbol} short-term trend is {trend}; wait for confirmation before execution.",
        "entry_window": "latest 10 ticks / latest candle snapshot",
        "preferred_flow": ["market", "risk", "compliance", "execution", "report"],
        "status": "ready",
    }
    summary = (
        f"我把目标拆成 5 步：先看 {symbol} 行情，再做风控和合规检查，条件满足才交给执行交易员。"
    )
    append_team_event(events, "策略研究员", "经理", summary, writer)
    remember_agent_report("strategy", plan)
    return plan


def risk_sentinel_agent(
    *,
    task: str,
    symbol: str,
    amount: float = 0.0,
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    append_team_event(events, "经理", "风控官", f"请检查账户与风险边界：{task}；symbol={symbol}, amount={amount}", writer)
    if not st.session_state.deriv_token:
        report = {
            "role": "Risk Sentinel",
            "ok": False,
            "status": "blocked",
            "reason": "missing_deriv_api_token",
        }
        append_team_event(events, "风控官", "经理", "我无法检查账户：还没有配置 Deriv API Token。", writer)
        remember_agent_report("risk", report)
        return report
    account_result = call_deriv_tool(
        "check_account_status",
        check_account_status(st.session_state.deriv_token),
        {"api_token": st.session_state.deriv_token},
        writer,
    )
    report = {
        "role": "Risk Sentinel",
        "ok": bool(account_result.get("ok")),
        "symbol": symbol,
        "amount": amount,
        "account": account_result.get("data"),
        "status": "cleared" if account_result.get("ok") else "blocked",
    }
    append_team_event(events, "风控官", "经理", "账户检查完成。若金额和方向明确，可进入合规审查和执行。", writer)
    remember_agent_report("risk", report)
    return report


def compliance_agent(
    *,
    task: str,
    amount: float = 0.0,
    contract_type: str = "",
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    append_team_event(events, "经理", "合规审查员", f"请审查指令是否清晰、安全：{task}", writer)
    blockers = []
    if has_trade_intent(task) and amount <= 0:
        blockers.append("missing_amount")
    if has_trade_intent(task) and contract_type not in {"CALL", "PUT"}:
        blockers.append("missing_direction")
    if any(word in task.lower() for word in ["all in", "满仓", "梭哈"]):
        blockers.append("excessive_risk_language")
    report = {
        "role": "Compliance Reviewer",
        "ok": not blockers,
        "blockers": blockers,
        "status": "cleared" if not blockers else "needs_clarification",
    }
    if blockers:
        summary = f"我发现需要补充或降风险的点：{', '.join(blockers)}。"
    else:
        summary = "合规检查通过：指令边界清楚，可以继续。"
    append_team_event(events, "合规审查员", "经理", summary, writer)
    remember_agent_report("compliance", report)
    return report


def chart_engineer_agent(
    *,
    task: str,
    symbol: str,
    granularity: int = 60,
    count: int = 120,
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    append_team_event(events, "经理", "图表工程师", f"请生成图表快照：{task}；symbol={symbol}, count={count}", writer)
    result = call_deriv_tool(
        "get_historical_candles",
        get_historical_candles(symbol, int(granularity), min(int(count), 1000)),
        {"symbol": symbol, "granularity": int(granularity), "count": min(int(count), 1000)},
        writer,
    )
    if result.get("ok"):
        add_chart_snapshot(result, source="chart_agent")
    report = {
        "role": "Chart Engineer",
        "ok": bool(result.get("ok")),
        "symbol": symbol,
        "granularity": granularity,
        "count": ((result.get("data") or {}).get("returned_count") or count),
        "snapshot_count": len(st.session_state.chart_snapshots),
    }
    append_team_event(
        events,
        "图表工程师",
        "经理",
        f"图表快照已生成：{symbol}，当前可切换快照 {len(st.session_state.chart_snapshots)} 张。"
        if result.get("ok")
        else f"图表生成失败：{(result.get('error') or {}).get('message', 'unknown error')}",
        writer,
    )
    remember_agent_report("chart", report)
    return report


def report_agent(
    *,
    task: str,
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    append_team_event(events, "经理", "报告员", f"请整理本轮任务复盘：{task}", writer)
    report = {
        "role": "Report Agent",
        "ok": True,
        "event_count": len(events),
        "active_agents": sorted(st.session_state.agent_reports.keys()),
        "chart_snapshots": len(st.session_state.chart_snapshots),
        "latest_receipt": ((st.session_state.last_trade_receipt or {}).get("data") or {}).get("receipt"),
    }
    append_team_event(events, "报告员", "经理", "我已整理执行时间线、活跃 Agent 和本地可审计记录。", writer)
    remember_agent_report("report", report)
    return report


def execution_agent(
    *,
    task: str,
    symbol: str,
    amount: float,
    contract_type: str,
    duration: int,
    duration_unit: str,
    risk_note: str = "Use demo token and execute within user-specified parameters.",
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    append_team_event(
        events,
        "经理",
        "执行交易员",
        (
            f"{task}；symbol={symbol}, amount={amount}, contract_type={contract_type}, "
            f"duration={duration}{duration_unit}；风控边界：{risk_note}"
        ),
        writer,
    )
    if not st.session_state.deriv_token:
        report = {
            "role": "Risk & Execution Agent",
            "ok": False,
            "status": "blocked",
            "reason": "missing_deriv_api_token",
        }
        append_team_event(
            events,
            "执行交易员",
            "经理",
            "无法执行：左侧未配置 Deriv API Token。请使用 demo token 后再下单。",
            writer,
        )
        return report

    account_result = call_deriv_tool(
        "check_account_status",
        check_account_status(st.session_state.deriv_token),
        {"api_token": st.session_state.deriv_token},
        writer,
    )
    account_ok = bool(account_result.get("ok"))
    receipt_result = call_deriv_tool(
        "execute_simulated_trade",
        execute_simulated_trade(
            st.session_state.deriv_token,
            symbol,
            float(amount),
            contract_type,
            int(duration),
            duration_unit,
        )
        ,
        {
            "api_token": st.session_state.deriv_token,
            "symbol": symbol,
            "amount": float(amount),
            "contract_type": contract_type,
            "duration": int(duration),
            "duration_unit": duration_unit,
        },
        writer,
    )
    if receipt_result.get("ok"):
        st.session_state.last_trade_receipt = receipt_result
        receipt = ((receipt_result.get("data") or {}).get("receipt") or {})
        report = {
            "role": "Execution Trader",
            "ok": True,
            "account_checked": account_ok,
            "account": account_result.get("data"),
            "receipt": receipt,
        }
        append_team_event(
            events,
            "执行交易员",
            "经理",
            (
                "下单成功，"
                f"合同ID: {receipt.get('contract_id')}，成交价: {receipt.get('purchase_price')} "
                f"{receipt.get('currency')}。"
            ),
            writer,
        )
        return report

    error_message = (receipt_result.get("error") or {}).get("message", "unknown error")
    report = {
        "role": "Execution Trader",
        "ok": False,
        "account_checked": account_ok,
        "account": account_result.get("data"),
        "error": error_message,
    }
    append_team_event(events, "执行交易员", "经理", f"下单失败：{error_message}", writer)
    return report


def assign_task_to_market_agent(
    arguments: dict[str, Any],
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    return market_analyst_agent(
        task=str(arguments.get("task") or "读取市场数据并判断趋势"),
        symbol=str(arguments.get("symbol") or DEFAULT_SYMBOL),
        tick_count=int(arguments.get("tick_count") or 10),
        granularity=int(arguments.get("granularity") or 60),
        candle_count=int(arguments.get("candle_count") or 60),
        analysis_goal=str(arguments.get("analysis_goal") or "tick_trend"),
        events=events,
        writer=writer,
    )


def assign_task_to_execution_agent(
    arguments: dict[str, Any],
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    return execution_agent(
        task=str(arguments.get("task") or "执行模拟盘订单"),
        symbol=str(arguments.get("symbol") or DEFAULT_SYMBOL),
        amount=float(arguments.get("amount") or 0),
        contract_type=str(arguments.get("contract_type") or "CALL").upper(),
        duration=int(arguments.get("duration") or 1),
        duration_unit=str(arguments.get("duration_unit") or "m"),
        risk_note=str(arguments.get("risk_note") or "经理批准的模拟盘交易。"),
        events=events,
        writer=writer,
    )


def assign_task_to_strategy_agent(
    arguments: dict[str, Any],
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    return strategy_agent(
        task=str(arguments.get("task") or "拆解交易目标"),
        symbol=str(arguments.get("symbol") or DEFAULT_SYMBOL),
        events=events,
        writer=writer,
    )


def assign_task_to_risk_agent(
    arguments: dict[str, Any],
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    return risk_sentinel_agent(
        task=str(arguments.get("task") or "检查账户与风险边界"),
        symbol=str(arguments.get("symbol") or DEFAULT_SYMBOL),
        amount=float(arguments.get("amount") or 0),
        events=events,
        writer=writer,
    )


def assign_task_to_compliance_agent(
    arguments: dict[str, Any],
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    return compliance_agent(
        task=str(arguments.get("task") or "审查交易指令"),
        amount=float(arguments.get("amount") or 0),
        contract_type=str(arguments.get("contract_type") or "").upper(),
        events=events,
        writer=writer,
    )


def assign_task_to_chart_agent(
    arguments: dict[str, Any],
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    return chart_engineer_agent(
        task=str(arguments.get("task") or "生成 K 线图表"),
        symbol=str(arguments.get("symbol") or DEFAULT_SYMBOL),
        granularity=int(arguments.get("granularity") or DEFAULT_GRANULARITY),
        count=int(arguments.get("count") or 120),
        events=events,
        writer=writer,
    )


def assign_task_to_report_agent(
    arguments: dict[str, Any],
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    return report_agent(
        task=str(arguments.get("task") or "整理团队复盘"),
        events=events,
        writer=writer,
    )


def manager_tool_dispatch(
    name: str,
    arguments: dict[str, Any],
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if name == "assign_task_to_market_agent":
        return assign_task_to_market_agent(arguments, events, writer)
    if name == "assign_task_to_execution_agent":
        return assign_task_to_execution_agent(arguments, events, writer)
    if name == "assign_task_to_strategy_agent":
        return assign_task_to_strategy_agent(arguments, events, writer)
    if name == "assign_task_to_risk_agent":
        return assign_task_to_risk_agent(arguments, events, writer)
    if name == "assign_task_to_compliance_agent":
        return assign_task_to_compliance_agent(arguments, events, writer)
    if name == "assign_task_to_chart_agent":
        return assign_task_to_chart_agent(arguments, events, writer)
    if name == "assign_task_to_report_agent":
        return assign_task_to_report_agent(arguments, events, writer)
    return {"ok": False, "error": f"unknown manager tool: {name}"}


def manager_with_openai_tool_calling(
    user_text: str,
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> TeamRunResult | None:
    try:
        from openai import OpenAI

        provider: Provider = st.session_state.llm_provider
        base_url = OPENAI_COMPATIBLE_BASE_URLS.get(provider)
        if provider == "OpenAI-Compatible":
            base_url = st.session_state.custom_base_url.strip() or None
            if not base_url:
                return None
        kwargs: dict[str, Any] = {"api_key": st.session_state.llm_api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": MANAGER_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]
        market_report = None
        execution_report = None
        agent_reports: dict[str, Any] = {}
        final_text = ""

        append_team_event(events, "用户", "经理", user_text, writer)
        for _ in range(5):
            response = client.chat.completions.create(
                model=st.session_state.llm_model,
                messages=messages,
                tools=MANAGER_TOOLS,
                tool_choice="auto",
                temperature=0.1,
            )
            message = response.choices[0].message
            messages.append(message.model_dump(exclude_none=True))
            tool_calls = message.tool_calls or []
            if not tool_calls:
                final_text = message.content or "经理已完成团队协同处理。"
                append_team_event(events, "经理", "用户", final_text, writer)
                break

            for tool_call in tool_calls:
                arguments = json.loads(tool_call.function.arguments or "{}")
                result = manager_tool_dispatch(tool_call.function.name, arguments, events, writer)
                agent_reports[tool_call.function.name] = result
                if tool_call.function.name == "assign_task_to_market_agent":
                    market_report = result
                elif tool_call.function.name == "assign_task_to_execution_agent":
                    execution_report = result
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

        if not final_text:
            final_text = deterministic_manager_summary(market_report, execution_report)
            append_team_event(events, "经理", "用户", final_text, writer)
        publish_team_log(events, build_team_extra_lines(market_report, execution_report))
        return TeamRunResult(
            final_answer=final_text,
            events=events,
            market_report=market_report,
            execution_report=execution_report,
            ok=not (execution_report and execution_report.get("ok") is False),
            agent_reports=agent_reports,
        )
    except Exception as exc:
        append_team_event(events, "系统", "经理", f"大模型 tool calling 失败，切换 Python 状态机：{exc}", writer)
        return None


def manager_with_anthropic_tool_calling(
    user_text: str,
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> TeamRunResult | None:
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=st.session_state.llm_api_key)
        anthropic_tools = [
            {
                "name": tool["function"]["name"],
                "description": tool["function"]["description"],
                "input_schema": tool["function"]["parameters"],
            }
            for tool in MANAGER_TOOLS
        ]
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_text}]
        market_report = None
        execution_report = None
        agent_reports: dict[str, Any] = {}
        final_text = ""

        append_team_event(events, "用户", "经理", user_text, writer)
        for _ in range(5):
            response = client.messages.create(
                model=st.session_state.llm_model,
                max_tokens=1400,
                temperature=0.1,
                system=MANAGER_SYSTEM_PROMPT,
                tools=anthropic_tools,
                messages=messages,
            )
            tool_results = []
            assistant_blocks = []
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    final_text += block.text
                    assistant_blocks.append({"type": "text", "text": block.text})
                elif getattr(block, "type", None) == "tool_use":
                    assistant_blocks.append(
                        {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                    )
                    result = manager_tool_dispatch(block.name, dict(block.input), events, writer)
                    agent_reports[block.name] = result
                    if block.name == "assign_task_to_market_agent":
                        market_report = result
                    elif block.name == "assign_task_to_execution_agent":
                        execution_report = result
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        }
                    )
            messages.append({"role": "assistant", "content": assistant_blocks})
            if not tool_results:
                break
            messages.append({"role": "user", "content": tool_results})

        final_text = final_text.strip() or deterministic_manager_summary(market_report, execution_report)
        append_team_event(events, "经理", "用户", final_text, writer)
        publish_team_log(events, build_team_extra_lines(market_report, execution_report))
        return TeamRunResult(
            final_answer=final_text,
            events=events,
            market_report=market_report,
            execution_report=execution_report,
            ok=not (execution_report and execution_report.get("ok") is False),
            agent_reports=agent_reports,
        )
    except Exception as exc:
        append_team_event(events, "系统", "经理", f"Anthropic tool calling 失败，切换 Python 状态机：{exc}", writer)
        return None


def build_team_extra_lines(
    market_report: dict[str, Any] | None,
    execution_report: dict[str, Any] | None,
) -> list[str]:
    lines: list[str] = []
    if market_report:
        tick_analysis = market_report.get("tick_analysis") or {}
        lines.extend(
            [
                "Market Analyst Structured Report:",
                json.dumps(
                    {
                        "symbol": market_report.get("symbol"),
                        "latest_quote": tick_analysis.get("latest_quote"),
                        "last_three": tick_analysis.get("last_three"),
                        "consecutive_three_down": tick_analysis.get("consecutive_three_down"),
                        "consecutive_three_up": tick_analysis.get("consecutive_three_up"),
                        "trend": tick_analysis.get("trend"),
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
            ]
        )
    if execution_report:
        safe_execution = dict(execution_report)
        safe_execution.pop("account", None)
        lines.extend(
            [
                "Risk & Execution Structured Report:",
                json.dumps(safe_execution, ensure_ascii=False, indent=2, default=str),
            ]
        )
    return lines


def deterministic_manager_summary(
    market_report: dict[str, Any] | None,
    execution_report: dict[str, Any] | None,
) -> str:
    if execution_report and execution_report.get("ok"):
        receipt = execution_report.get("receipt") or {}
        return (
            "经理总结：行情员工完成市场检查，执行交易员已通过模拟盘下单。"
            f"合同 ID：{receipt.get('contract_id')}，成交价：{receipt.get('purchase_price')}。"
        )
    if execution_report and not execution_report.get("ok"):
        return f"经理总结：交易未完成，原因：{execution_report.get('reason') or execution_report.get('error')}。"
    if market_report:
        return f"经理总结：{market_report.get('summary')}"
    return "经理总结：当前指令没有形成可执行交易任务。"


def deterministic_manager_state_machine(
    user_text: str,
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> TeamRunResult:
    append_team_event(events, "用户", "经理", user_text, writer)
    symbol = extract_symbol(user_text)
    market_report = None
    execution_report = None
    agent_reports: dict[str, Any] = {}

    trade_intent = has_trade_intent(user_text)
    amount = extract_amount(user_text)
    contract_type = extract_contract_type(user_text)
    strategy_report = assign_task_to_strategy_agent(
        {"task": user_text, "symbol": symbol},
        events,
        writer,
    )
    agent_reports["strategy"] = strategy_report
    needs_market = trade_intent or any(
        keyword in user_text for keyword in ["走势", "Tick", "tick", "行情", "价格", "K线", "k线", "连续", "图", "chart"]
    )
    if needs_market:
        market_report = assign_task_to_market_agent(
            {
                "task": "去抓取最新 Tick，并判断是否满足用户描述的趋势条件。",
                "symbol": symbol,
                "tick_count": 10,
                "granularity": extract_granularity(user_text),
                "candle_count": extract_count(user_text),
                "analysis_goal": "consecutive_down" if "跌" in user_text else "tick_trend",
            },
            events,
            writer,
        )
        agent_reports["market"] = market_report

    if any(keyword in user_text for keyword in ["图", "K线", "k线", "chart", "表格", "走势"]):
        agent_reports["chart"] = assign_task_to_chart_agent(
            {
                "task": "生成新的 K 线图表快照，供老板切换查看。",
                "symbol": symbol,
                "granularity": extract_granularity(user_text),
                "count": extract_count(user_text) if extract_count(user_text) > 0 else 120,
            },
            events,
            writer,
        )

    if trade_intent:
        duration = extract_duration(user_text)
        duration_unit = extract_duration_unit(user_text)
        if duration <= 0:
            duration = 5
            duration_unit = "t"
        risk_report = assign_task_to_risk_agent(
            {"task": user_text, "symbol": symbol, "amount": amount},
            events,
            writer,
        )
        compliance_report = assign_task_to_compliance_agent(
            {"task": user_text, "amount": amount, "contract_type": contract_type or ""},
            events,
            writer,
        )
        agent_reports["risk"] = risk_report
        agent_reports["compliance"] = compliance_report
        missing = []
        if amount <= 0:
            missing.append("金额 amount")
        if contract_type not in {"CALL", "PUT"}:
            missing.append("方向 CALL/PUT")
        if missing:
            message = f"缺少交易参数：{', '.join(missing)}。请补充后我再派执行交易员。"
            append_team_event(events, "经理", "用户", message, writer)
            publish_team_log(events, build_team_extra_lines(market_report, execution_report))
            return TeamRunResult(message, events, market_report, execution_report, ok=False, agent_reports=agent_reports)

        condition_requires_down = "连续" in user_text and "跌" in user_text
        condition_requires_up = "连续" in user_text and "涨" in user_text
        tick_analysis = (market_report or {}).get("tick_analysis") or {}
        condition_passed = True
        condition_note = "用户未设置市场条件，风控允许直接模拟执行。"
        if condition_requires_down:
            condition_passed = bool(tick_analysis.get("consecutive_three_down"))
            condition_note = f"连续三个 Tick 下跌条件 -> {condition_passed}"
        elif condition_requires_up:
            condition_passed = bool(tick_analysis.get("consecutive_three_up"))
            condition_note = f"连续三个 Tick 上涨条件 -> {condition_passed}"
        numeric_condition = extract_condition(user_text)
        if numeric_condition and tick_analysis.get("latest_quote") is not None:
            condition_passed, condition_note = evaluate_condition(
                numeric_condition, float(tick_analysis["latest_quote"])
            )

        append_team_event(events, "经理", "经理", f"风控条件判断：{condition_note}", writer)
        compliance_ok = bool((agent_reports.get("compliance") or {}).get("ok", True))
        risk_hard_block = (agent_reports.get("risk") or {}).get("reason") not in {None, "missing_deriv_api_token"}
        if condition_passed and compliance_ok and not risk_hard_block:
            execution_report = assign_task_to_execution_agent(
                {
                    "task": "条件已满足，立刻执行用户授权的模拟盘订单。",
                    "symbol": symbol,
                    "amount": amount,
                    "contract_type": contract_type,
                    "duration": duration,
                    "duration_unit": duration_unit,
                    "risk_note": condition_note,
                },
                events,
                writer,
            )
            agent_reports["execution"] = execution_report
        else:
            append_team_event(
                events,
                "经理",
                "执行交易员",
                "条件未满足，暂停下单，不触发 execute_simulated_trade。",
                writer,
            )

    agent_reports["report"] = assign_task_to_report_agent(
        {"task": "整理本轮多智能体交易协作复盘。"},
        events,
        writer,
    )
    final_answer = deterministic_manager_summary(market_report, execution_report)
    append_team_event(events, "经理", "用户", final_answer, writer)
    publish_team_log(events, build_team_extra_lines(market_report, execution_report))
    return TeamRunResult(
        final_answer=final_answer,
        events=events,
        market_report=market_report,
        execution_report=execution_report,
        ok=not (execution_report and execution_report.get("ok") is False),
        agent_reports=agent_reports,
    )


def run_hierarchical_trading_team(
    user_text: str,
    writer: Callable[[str], None] | None = None,
) -> TeamRunResult:
    events: list[AgentEvent] = []
    provider: Provider = st.session_state.llm_provider
    if provider in {"OpenAI", "DeepSeek", "OpenAI-Compatible"} and st.session_state.llm_api_key:
        result = manager_with_openai_tool_calling(user_text, events, writer)
        if result:
            return result
    if provider == "Anthropic" and st.session_state.llm_api_key:
        result = manager_with_anthropic_tool_calling(user_text, events, writer)
        if result:
            return result
    return deterministic_manager_state_machine(user_text, events, writer)


def reset_agent_log() -> list[str]:
    started_at = datetime.now(timezone.utc).isoformat()
    return [
        "Deriv Smart Trading Gateway · Agent Execution Trace",
        f"started_at: {started_at}",
        "mode: simulated_trade_execution",
        "-" * 72,
    ]


def publish_agent_log(lines: list[str]) -> None:
    st.session_state.agent_execution_log = "\n".join(lines)


def condition_to_text(condition: dict[str, Any] | None) -> str:
    if not condition:
        return "无条件，读取行情后直接触发模拟下单"
    return f"{condition.get('metric')} {condition.get('operator')} {condition.get('value')}"


def evaluate_condition(condition: dict[str, Any] | None, latest_quote: float) -> tuple[bool, str]:
    if not condition:
        return True, "未设置条件，允许自动执行"
    operator = condition.get("operator")
    value = float(condition.get("value"))
    checks = {
        ">": latest_quote > value,
        ">=": latest_quote >= value,
        "<": latest_quote < value,
        "<=": latest_quote <= value,
        "==": latest_quote == value,
    }
    passed = bool(checks.get(operator, False))
    return passed, f"latest_tick={latest_quote} {operator} {value} -> {passed}"


def execute_trade_closed_loop(plan: ToolPlan) -> tuple[dict[str, Any], str]:
    log = reset_agent_log()
    params = plan.params
    safe_params = dict(params)
    safe_params.pop("api_token", None)
    log.append(f"1. 解析交易意图: action=execute_simulated_trade")
    log.append(f"   params={json.dumps(safe_params, ensure_ascii=False, default=str)}")
    log.append(f"   rationale={plan.rationale}")
    log.append(f"2. 数据读取: get_market_ticks(symbol={params['symbol']}, subscribe=False)")

    tick_result = call_deriv_tool(
        "get_market_ticks",
        get_market_ticks(params["symbol"], False),
        {"symbol": params["symbol"], "subscribe": False},
    )
    st.session_state.last_tick = tick_result
    if not tick_result.get("ok"):
        log.append("   read_status=FAILED")
        log.append(f"   error={(tick_result.get('error') or {}).get('message', 'unknown error')}")
        log.append("3. 条件判断: SKIPPED")
        log.append("4. 自动触发下单: ABORTED")
        publish_agent_log(log)
        return tick_result, summarize_result(plan, tick_result)

    tick = ((tick_result.get("data") or {}).get("tick") or {})
    latest_quote = float(tick.get("quote"))
    log.append("   read_status=OK")
    log.append(f"   latest_tick={latest_quote}")
    log.append(f"   tick_timestamp={tick.get('timestamp')}")
    log.append(f"3. 条件判断: {condition_to_text(params.get('condition'))}")

    condition_passed, condition_detail = evaluate_condition(params.get("condition"), latest_quote)
    log.append(f"   condition_result={condition_detail}")
    if not condition_passed:
        result = {
            "ok": True,
            "tool": "execute_simulated_trade",
            "data": {
                "status": "skipped",
                "reason": "condition_not_met",
                "latest_tick": latest_quote,
                "condition": params.get("condition"),
            },
        }
        log.append("4. 自动触发下单: SKIPPED")
        log.append("   reason=condition_not_met")
        publish_agent_log(log)
        return result, "条件没有满足，智能体没有触发模拟下单。执行链条已写入自动执行日志。"

    log.append("4. 自动触发下单: READY")
    if not st.session_state.deriv_token:
        result = {
            "ok": False,
            "error": {"message": "请先在左侧配置 Deriv API Token。建议使用 demo token。"},
        }
        log.append("   order_status=ABORTED")
        log.append("   reason=missing_deriv_api_token")
        publish_agent_log(log)
        return result, summarize_result(plan, result)

    log.append("   token_status=configured(masked)")
    log.append(
        "   tool_call=execute_simulated_trade("
        f"symbol={params['symbol']}, amount={params['amount']}, "
        f"contract_type={params['contract_type']}, duration={params['duration']}, "
        f"duration_unit={params['duration_unit']})"
    )
    result = call_deriv_tool(
        "execute_simulated_trade",
        execute_simulated_trade(
            st.session_state.deriv_token,
            params["symbol"],
            params["amount"],
            params["contract_type"],
            params["duration"],
            params["duration_unit"],
        ),
        {
            "api_token": st.session_state.deriv_token,
            "symbol": params["symbol"],
            "amount": params["amount"],
            "contract_type": params["contract_type"],
            "duration": params["duration"],
            "duration_unit": params["duration_unit"],
        },
    )

    if result.get("ok"):
        st.session_state.last_trade_receipt = result
        receipt = ((result.get("data") or {}).get("receipt") or {})
        log.append("   order_status=SUCCESS")
        log.append(f"   contract_id={receipt.get('contract_id')}")
        log.append(f"   purchase_price={receipt.get('purchase_price')}")
        log.append(f"   transaction_id={receipt.get('transaction_id')}")
    else:
        log.append("   order_status=FAILED")
        log.append(f"   error={(result.get('error') or {}).get('message', 'unknown error')}")

    publish_agent_log(log)
    return result, summarize_result(plan, result)


def execute_plan(plan: ToolPlan) -> tuple[dict[str, Any], str]:
    st.session_state.last_plan = {
        "action": plan.action,
        "params": plan.params,
        "rationale": plan.rationale,
    }

    if plan.action == "get_market_ticks":
        log = reset_agent_log()
        log.append(f"1. 数据读取: get_market_ticks(symbol={plan.params['symbol']}, subscribe={plan.params.get('subscribe', False)})")
        result = call_deriv_tool(
            "get_market_ticks",
            get_market_ticks(plan.params["symbol"], plan.params.get("subscribe", False)),
            {"symbol": plan.params["symbol"], "subscribe": plan.params.get("subscribe", False)},
        )
        st.session_state.last_tick = result
        log.append(f"   read_status={'OK' if result.get('ok') else 'FAILED'}")
        log.append("2. 条件判断: 无")
        log.append("3. 自动触发下单: 无交易意图")
        publish_agent_log(log)
        return result, summarize_result(plan, result)

    if plan.action == "get_historical_candles":
        log = reset_agent_log()
        log.append(
            "1. 数据读取: get_historical_candles("
            f"symbol={plan.params['symbol']}, granularity={plan.params['granularity']}, count={plan.params['count']})"
        )
        result = call_deriv_tool(
            "get_historical_candles",
            get_historical_candles(
                plan.params["symbol"],
                plan.params["granularity"],
                plan.params["count"],
            ),
            {
                "symbol": plan.params["symbol"],
                "granularity": plan.params["granularity"],
                "count": plan.params["count"],
            },
        )
        add_chart_snapshot(result, source="execute_plan")
        log.append(f"   read_status={'OK' if result.get('ok') else 'FAILED'}")
        log.append(f"   returned_count={(result.get('data') or {}).get('returned_count')}")
        log.append("2. 条件判断: 无")
        log.append("3. 自动触发下单: 无交易意图")
        publish_agent_log(log)
        return result, summarize_result(plan, result)

    if plan.action == "execute_simulated_trade":
        return execute_trade_closed_loop(plan)

    publish_agent_log(reset_agent_log() + ["1. 普通对话: 未触发工具", "2. 自动触发下单: 无"])
    return {"ok": True, "data": {}}, "我可以帮你查最新 tick、画 K 线，或执行模拟交易。请给出 symbol、方向、金额和时长。"


def summarize_result(plan: ToolPlan, result: dict[str, Any]) -> str:
    if not result.get("ok"):
        message = (result.get("error") or {}).get("message", "工具调用失败")
        return f"工具调用没有成功：{message}"

    if plan.action == "get_market_ticks":
        tick = ((result.get("data") or {}).get("tick") or {})
        return f"{tick.get('symbol')} 最新报价是 {tick.get('quote')}，时间 {tick.get('timestamp')}。"

    if plan.action == "get_historical_candles":
        data = result.get("data") or {}
        return f"已获取 {data.get('symbol')} 的 {data.get('returned_count')} 根 K 线，并在下方绘制成蜡烛图。"

    if plan.action == "execute_simulated_trade":
        data = result.get("data") or {}
        if data.get("status") == "skipped":
            return (
                "条件没有满足，未触发模拟交易。"
                f"最新价：{data.get('latest_tick')}，条件：{data.get('condition')}。"
            )
        receipt = ((result.get("data") or {}).get("receipt") or {})
        return (
            "模拟交易已提交成功。"
            f"合约 ID：{receipt.get('contract_id')}，成交价：{receipt.get('purchase_price')} "
            f"{receipt.get('currency')}。"
        )

    return "已完成。"


def stream_text(text: str) -> Generator[str, None, None]:
    for char in text:
        yield char
        time.sleep(0.01)


def render_header() -> None:
    st.markdown(
        f"""
        <div class="terminal-hero">
          <div class="terminal-hero-top">
            <div>
              <div class="terminal-kicker">{html.escape(t("hero_kicker"))}</div>
              <div class="terminal-title">{html.escape(t("hero_title"))}</div>
              <div class="terminal-subtitle">
                {html.escape(t("hero_subtitle"))}
              </div>
            </div>
            <div class="live-chip">LIVE · MCP WS</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def readable_agent_bubble(agent_id: str) -> str:
    events = st.session_state.get("team_events", [])
    spec = AGENT_SPECS[agent_id]
    role_names = {spec["zh_name"], spec["en_name"]}
    if agent_id == "execution":
        role_names.update({"风控执行员", "Risk & Execution Agent"})
    manager_names = {"经理", "Manager"}
    task_prefix = t("market_task_prefix") if agent_id in {"market", "chart"} else t("execution_task_prefix")
    report_prefix = t("market_report_prefix") if agent_id in {"market", "chart"} else t("execution_report_prefix")
    default_text = agent_state_fallback(agent_id)

    for line in reversed(events):
        if not any(role_name in line for role_name in role_names):
            continue
        message = re.split(r"：|: ", line, maxsplit=1)[-1].strip()
        if current_lang() == "en" and has_cjk(message):
            message = agent_state_fallback(agent_id)
        is_report = any(f"{role_name} ➔ {manager}" in line for role_name in role_names for manager in manager_names)
        is_task = any(f"{manager} ➔ {role_name}" in line for role_name in role_names for manager in manager_names)
        separator = "：" if current_lang() == "zh" else ": "
        if is_report:
            return f"<strong>{html.escape(report_prefix)}{separator}</strong>{html.escape(message)}"
        if is_task:
            return f"<strong>{html.escape(task_prefix)}{separator}</strong>{html.escape(message)}"
    return html.escape(default_text)


def active_agent_ids() -> set[str]:
    active = set(st.session_state.get("agent_reports", {}).keys())
    text = "\n".join(st.session_state.get("team_events", []))
    for agent_id, spec in AGENT_SPECS.items():
        if spec["zh_name"] in text or spec["en_name"] in text:
            active.add(agent_id)
    if st.session_state.get("team_events"):
        active.add("manager")
    return active


def render_swarm_graph() -> None:
    st.markdown(f"### {t('swarm_graph')}")
    st.markdown(f'<p class="small-muted">{html.escape(t("swarm_graph_caption"))}</p>', unsafe_allow_html=True)
    active = active_agent_ids()
    worker_ids = ["strategy", "market", "risk", "compliance", "chart", "execution", "report"]
    nodes = []
    for agent_id in ["manager"] + worker_ids:
        spec = AGENT_SPECS[agent_id]
        report = st.session_state.agent_reports.get(agent_id, {}).get("report", {})
        nodes.append(
            {
                "id": agent_id,
                "label": agent_name(agent_id),
                "code": spec["code"],
                "type": "system" if agent_id == "manager" else ("risk" if agent_id in {"risk", "compliance"} else "task"),
                "description": agent_role(agent_id),
                "importance": 1.0 if agent_id == "manager" else (0.78 if agent_id in active else 0.55),
                "confidence": 0.98 if agent_id in active or agent_id == "manager" else 0.72,
                "color": spec["color"],
                "active": agent_id in active,
                "tags": ["manager", "orchestrator"] if agent_id == "manager" else ["agent", agent_id],
                "metadata": {
                    "status": "active" if agent_id in active else "standby",
                    "last_update": st.session_state.agent_reports.get(agent_id, {}).get("updated_at", "-"),
                    "report_keys": ", ".join(report.keys()) if isinstance(report, dict) else "-",
                },
            }
        )

    links = [
        {"source": "manager", "target": "strategy", "label": "DECOMPOSES", "strength": 0.95},
        {"source": "strategy", "target": "market", "label": "REQUESTS_SIGNAL", "strength": 0.86},
        {"source": "strategy", "target": "risk", "label": "SETS_BOUNDARY", "strength": 0.78},
        {"source": "risk", "target": "compliance", "label": "VALIDATES", "strength": 0.84},
        {"source": "market", "target": "chart", "label": "VISUALIZES", "strength": 0.76},
        {"source": "compliance", "target": "execution", "label": "APPROVES", "strength": 0.88},
        {"source": "execution", "target": "report", "label": "RECEIPT_TO", "strength": 0.82},
        {"source": "report", "target": "manager", "label": "SUMMARIZES", "strength": 0.72},
        {"source": "manager", "target": "market", "label": "ASSIGNS", "strength": 0.7},
        {"source": "manager", "target": "execution", "label": "AUTHORIZES", "strength": 0.7},
    ]
    graph = {
        "nodes": nodes,
        "links": links,
        "status": {
            "nodes": len(nodes),
            "links": len(links),
            "active": len(active),
            "updated": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S MYT"),
        },
    }
    graph_json = json.dumps(graph, ensure_ascii=False)
    title = html.escape(t("swarm_graph"))
    status_nodes = "Nodes" if current_lang() == "en" else "节点"
    status_links = "Relations" if current_lang() == "en" else "关系"
    status_layout = "Layout: Active" if current_lang() == "en" else "布局：运行中"
    details_title = "Node Details" if current_lang() == "en" else "节点详情"
    toolbar = {
        "refresh": "Refresh Layout" if current_lang() == "en" else "刷新布局",
        "reset": "Reset Zoom" if current_lang() == "en" else "重置缩放",
        "labels": "Show Edge Labels" if current_lang() == "en" else "显示边标签",
        "add": "Add Mock Node" if current_lang() == "en" else "新增模拟节点",
        "fit": "Fit View" if current_lang() == "en" else "适配视图",
    }
    component = f"""
    <div id="kg-root">
      <div class="kg-toolbar">
        <div class="kg-title">{title}</div>
        <div class="kg-actions">
          <button id="kg-refresh">{html.escape(toolbar["refresh"])}</button>
          <button id="kg-reset">{html.escape(toolbar["reset"])}</button>
          <button id="kg-fit">{html.escape(toolbar["fit"])}</button>
          <label class="kg-switch"><input id="kg-labels" type="checkbox" checked><span>{html.escape(toolbar["labels"])}</span></label>
          <button id="kg-add">{html.escape(toolbar["add"])}</button>
        </div>
      </div>
      <canvas id="kg-canvas"></canvas>
      <div id="kg-legend"></div>
      <aside id="kg-panel">
        <button id="kg-close">×</button>
        <h3>{details_title}</h3>
        <div id="kg-panel-body"></div>
      </aside>
      <div id="kg-status"></div>
    </div>
    <style>
      #kg-root {{
        position: relative;
        height: 520px;
        overflow: hidden;
        border: 1px solid rgba(38, 59, 52, .55);
        background:
          radial-gradient(circle at 50% 44%, rgba(0,184,148,.09), transparent 38%),
          radial-gradient(circle at 82% 18%, rgba(122,167,255,.12), transparent 26%),
          radial-gradient(circle, rgba(8,17,15,.08) 1px, transparent 1px),
          linear-gradient(180deg, rgba(248,252,250,.96), rgba(236,245,241,.91));
        background-size: auto, auto, 18px 18px, auto;
        color: #10221d;
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        box-shadow: 0 22px 70px rgba(0,0,0,.22);
      }}
      #kg-canvas {{
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        cursor: grab;
      }}
      #kg-canvas.dragging {{ cursor: grabbing; }}
      .kg-toolbar {{
        position: absolute;
        z-index: 4;
        top: 14px;
        left: 14px;
        right: 14px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        pointer-events: none;
      }}
      .kg-title {{
        pointer-events: auto;
        color: #0a1915;
        font-weight: 900;
        letter-spacing: .01em;
        font-size: 16px;
        padding: 8px 11px;
        border: 1px solid rgba(255,255,255,.72);
        background: rgba(255,255,255,.68);
        backdrop-filter: blur(12px);
        box-shadow: 0 12px 34px rgba(16,34,29,.12);
      }}
      .kg-actions {{
        pointer-events: auto;
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        justify-content: flex-end;
      }}
      .kg-actions button, .kg-switch {{
        border: 1px solid rgba(30,54,48,.14);
        background: rgba(255,255,255,.72);
        color: #18342e;
        padding: 8px 10px;
        font-weight: 800;
        font-size: 12px;
        border-radius: 999px;
        box-shadow: 0 12px 34px rgba(16,34,29,.12);
        backdrop-filter: blur(12px);
      }}
      .kg-actions button:hover {{ transform: translateY(-1px); background: rgba(255,255,255,.92); }}
      .kg-switch {{ display: inline-flex; align-items: center; gap: 6px; }}
      .kg-switch input {{ accent-color: #7c3aed; }}
      #kg-legend {{
        position: absolute;
        z-index: 4;
        left: 14px;
        bottom: 46px;
        display: grid;
        gap: 5px;
        padding: 10px;
        border: 1px solid rgba(255,255,255,.72);
        background: rgba(255,255,255,.66);
        backdrop-filter: blur(12px);
        box-shadow: 0 12px 34px rgba(16,34,29,.12);
        min-width: 150px;
      }}
      .kg-legend-row {{ display: flex; align-items: center; justify-content: space-between; gap: 14px; font-size: 12px; color: #29443d; }}
      .kg-dot {{ width: 9px; height: 9px; border-radius: 50%; display: inline-block; margin-right: 7px; }}
      #kg-panel {{
        position: absolute;
        z-index: 5;
        top: 70px;
        right: 14px;
        width: min(310px, calc(100% - 28px));
        max-height: 390px;
        overflow: auto;
        padding: 15px;
        border: 1px solid rgba(255,255,255,.76);
        background: rgba(255,255,255,.76);
        backdrop-filter: blur(16px);
        box-shadow: 0 18px 54px rgba(16,34,29,.18);
        transform: translateX(115%);
        opacity: 0;
        transition: .22s ease;
      }}
      #kg-panel.open {{ transform: translateX(0); opacity: 1; }}
      #kg-close {{
        position: absolute;
        top: 9px;
        right: 9px;
        border: 0;
        background: rgba(16,34,29,.08);
        width: 25px;
        height: 25px;
        border-radius: 50%;
        font-weight: 900;
      }}
      #kg-panel h3 {{ margin: 0 28px 10px 0; font-size: 16px; color: #0f251f; }}
      .kg-panel-type {{ display: inline-block; padding: 3px 8px; border-radius: 999px; color: white; font-size: 11px; font-weight: 900; margin-bottom: 8px; }}
      .kg-panel-section {{ margin-top: 10px; font-size: 12px; color: #36534b; line-height: 1.45; }}
      .kg-panel-section strong {{ color: #0f251f; }}
      #kg-status {{
        position: absolute;
        z-index: 4;
        left: 14px;
        right: 14px;
        bottom: 12px;
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
        color: #29443d;
        font-size: 12px;
        font-weight: 800;
        padding: 8px 10px;
        border: 1px solid rgba(255,255,255,.7);
        background: rgba(255,255,255,.62);
        backdrop-filter: blur(12px);
      }}
      @media (max-width: 760px) {{
        #kg-root {{ height: 640px; }}
        .kg-toolbar {{ align-items: flex-start; flex-direction: column; }}
        #kg-panel {{ top: 132px; }}
      }}
    </style>
    <script>
    (() => {{
      const graph = {graph_json};
      const root = document.getElementById('kg-root');
      const canvas = document.getElementById('kg-canvas');
      const ctx = canvas.getContext('2d');
      const panel = document.getElementById('kg-panel');
      const panelBody = document.getElementById('kg-panel-body');
      const legend = document.getElementById('kg-legend');
      const status = document.getElementById('kg-status');
      let showLabels = true;
      let hovered = null, selected = null, dragging = null;
      let pan = {{ x: 0, y: 0 }}, zoom = 1, isPanning = false, last = {{x:0,y:0}};
      let alpha = 1;
      const colors = {{ system:'#8b5cf6', task:'#14b8a6', risk:'#f43f5e', concept:'#06b6d4', api:'#ef4444' }};
      const nodes = graph.nodes.map((n, i) => ({{
        ...n,
        x: Math.cos(i / graph.nodes.length * Math.PI * 2) * 170,
        y: Math.sin(i / graph.nodes.length * Math.PI * 2) * 130,
        vx: 0, vy: 0,
        radius: (n.id === 'manager' ? 34 : 22) + (n.importance || .5) * 12,
      }}));
      const byId = new Map(nodes.map(n => [n.id, n]));
      const links = graph.links.map(l => ({{ ...l, source: byId.get(l.source), target: byId.get(l.target) }})).filter(l => l.source && l.target);

      function resize() {{
        const rect = root.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        canvas.style.width = rect.width + 'px';
        canvas.style.height = rect.height + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }}
      function world(screenX, screenY) {{
        const rect = canvas.getBoundingClientRect();
        return {{
          x: (screenX - rect.left - rect.width / 2 - pan.x) / zoom,
          y: (screenY - rect.top - rect.height / 2 - pan.y) / zoom,
        }};
      }}
      function screen(node) {{
        const rect = canvas.getBoundingClientRect();
        return {{ x: rect.width / 2 + pan.x + node.x * zoom, y: rect.height / 2 + pan.y + node.y * zoom }};
      }}
      function related(node) {{
        if (!node) return new Set();
        const set = new Set([node.id]);
        links.forEach(l => {{
          if (l.source.id === node.id) set.add(l.target.id);
          if (l.target.id === node.id) set.add(l.source.id);
        }});
        return set;
      }}
      function tick() {{
        const center = byId.get('manager');
        if (center) {{
          center.x *= .94; center.y *= .94; center.vx *= .45; center.vy *= .45;
        }}
        for (let i = 0; i < nodes.length; i++) {{
          for (let j = i + 1; j < nodes.length; j++) {{
            const a = nodes[i], b = nodes[j];
            let dx = b.x - a.x, dy = b.y - a.y;
            let dist = Math.max(1, Math.hypot(dx, dy));
            const force = (3600 / (dist * dist)) * alpha;
            dx /= dist; dy /= dist;
            a.vx -= dx * force; a.vy -= dy * force;
            b.vx += dx * force; b.vy += dy * force;
          }}
        }}
        links.forEach(l => {{
          const targetDist = 142 + (1 - (l.strength || .75)) * 120;
          let dx = l.target.x - l.source.x, dy = l.target.y - l.source.y;
          const dist = Math.max(1, Math.hypot(dx, dy));
          const force = (dist - targetDist) * .012 * alpha;
          dx /= dist; dy /= dist;
          l.source.vx += dx * force; l.source.vy += dy * force;
          l.target.vx -= dx * force; l.target.vy -= dy * force;
        }});
        nodes.forEach(n => {{
          if (n === dragging) return;
          n.vx *= .86; n.vy *= .86;
          n.x += n.vx; n.y += n.vy;
        }});
        alpha = Math.max(.045, alpha * .992);
      }}
      function draw() {{
        tick();
        const rect = canvas.getBoundingClientRect();
        ctx.clearRect(0, 0, rect.width, rect.height);
        ctx.save();
        ctx.translate(rect.width / 2 + pan.x, rect.height / 2 + pan.y);
        ctx.scale(zoom, zoom);
        const focus = selected || hovered;
        const neighborhood = related(focus);
        const time = performance.now() / 1000;

        links.forEach(l => {{
          const active = !focus || (neighborhood.has(l.source.id) && neighborhood.has(l.target.id));
          ctx.globalAlpha = active ? .72 : .12;
          ctx.strokeStyle = active ? 'rgba(39,78,69,.62)' : 'rgba(42,61,56,.22)';
          ctx.lineWidth = active ? 1.7 / zoom : 1 / zoom;
          ctx.beginPath();
          ctx.moveTo(l.source.x, l.source.y);
          ctx.lineTo(l.target.x, l.target.y);
          ctx.stroke();
          if (active) {{
            const t = (time * .28 + (l.strength || .5)) % 1;
            const px = l.source.x + (l.target.x - l.source.x) * t;
            const py = l.source.y + (l.target.y - l.source.y) * t;
            ctx.globalAlpha = .72;
            ctx.fillStyle = '#00b894';
            ctx.beginPath(); ctx.arc(px, py, 3.2 / zoom, 0, Math.PI * 2); ctx.fill();
          }}
          if (showLabels && active) {{
            const mx = (l.source.x + l.target.x) / 2;
            const my = (l.source.y + l.target.y) / 2;
            ctx.font = `${{11 / zoom}}px system-ui`;
            const w = ctx.measureText(l.label).width + 12 / zoom;
            ctx.globalAlpha = .9;
            ctx.fillStyle = 'rgba(255,255,255,.82)';
            ctx.fillRect(mx - w / 2, my - 9 / zoom, w, 18 / zoom);
            ctx.fillStyle = '#35544c';
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText(l.label, mx, my);
          }}
        }});

        nodes.forEach(n => {{
          const isFocus = focus && neighborhood.has(n.id);
          const isDim = focus && !isFocus;
          const pulse = Math.sin(time * 2.2 + n.x * .01) * 2.2;
          const r = n.radius + pulse + (n === hovered ? 5 : 0);
          ctx.globalAlpha = isDim ? .22 : (n.confidence || .85);
          if (n === selected || n.id === 'manager') {{
            const halo = ctx.createRadialGradient(n.x, n.y, r * .4, n.x, n.y, r * 1.9);
            halo.addColorStop(0, (n.color || colors[n.type] || '#14b8a6') + '66');
            halo.addColorStop(1, 'rgba(255,255,255,0)');
            ctx.fillStyle = halo;
            ctx.beginPath(); ctx.arc(n.x, n.y, r * 1.9, 0, Math.PI * 2); ctx.fill();
          }}
          ctx.fillStyle = n.color || colors[n.type] || '#14b8a6';
          ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, Math.PI * 2); ctx.fill();
          ctx.strokeStyle = 'rgba(255,255,255,.9)';
          ctx.lineWidth = 2 / zoom;
          ctx.stroke();
          ctx.fillStyle = '#fff';
          ctx.font = `900 ${{13 / zoom}}px system-ui`;
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText(n.code || n.label.slice(0, 2), n.x, n.y);
          ctx.fillStyle = '#17312b';
          ctx.font = `800 ${{12 / zoom}}px system-ui`;
          ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
          ctx.fillText(n.label, n.x + r + 8 / zoom, n.y);
        }});
        ctx.restore();
        renderStatus();
        requestAnimationFrame(draw);
      }}
      function hit(screenX, screenY) {{
        const p = world(screenX, screenY);
        for (let i = nodes.length - 1; i >= 0; i--) {{
          const n = nodes[i];
          if (Math.hypot(p.x - n.x, p.y - n.y) < n.radius + 8) return n;
        }}
        return null;
      }}
      function openPanel(node) {{
        selected = node;
        if (!node) {{ panel.classList.remove('open'); return; }}
        const rels = links.filter(l => l.source.id === node.id || l.target.id === node.id)
          .map(l => `<li><strong>${{l.source.id === node.id ? 'OUT' : 'IN'}}</strong> ${{l.label}} · ${{l.source.id === node.id ? l.target.label : l.source.label}}</li>`).join('');
        panelBody.innerHTML = `
          <div class="kg-panel-type" style="background:${{node.color}}">${{node.type}}</div>
          <h3>${{node.label}}</h3>
          <div class="kg-panel-section">${{node.description || ''}}</div>
          <div class="kg-panel-section"><strong>Importance:</strong> ${{node.importance}}</div>
          <div class="kg-panel-section"><strong>Confidence:</strong> ${{node.confidence}}</div>
          <div class="kg-panel-section"><strong>Tags:</strong> ${{(node.tags || []).join(', ')}}</div>
          <div class="kg-panel-section"><strong>Metadata:</strong><br>${{Object.entries(node.metadata || {{}}).map(([k,v]) => `${{k}}: ${{v}}`).join('<br>')}}</div>
          <div class="kg-panel-section"><strong>Connected Relations:</strong><ul>${{rels}}</ul></div>
        `;
        panel.classList.add('open');
      }}
      function renderLegend() {{
        const counts = {{}};
        nodes.forEach(n => counts[n.type] = (counts[n.type] || 0) + 1);
        legend.innerHTML = Object.entries(counts).map(([type, count]) =>
          `<div class="kg-legend-row"><span><i class="kg-dot" style="background:${{colors[type] || '#14b8a6'}}"></i>${{type}}</span><strong>${{count}}</strong></div>`
        ).join('');
      }}
      function renderStatus() {{
        status.innerHTML = `<span>{status_nodes}: ${{nodes.length}}</span><span>{status_links}: ${{links.length}}</span><span>${{selected ? 'Selected: ' + selected.label : 'Selected: -'}}</span><span>${{hovered ? 'Hovered: ' + hovered.label : 'Hovered: -'}}</span><span>{status_layout}</span><span>Memory Sync: Simulated</span><span>${{graph.status.updated}}</span>`;
      }}
      canvas.addEventListener('mousemove', e => {{
        if (dragging) {{ const p = world(e.clientX, e.clientY); dragging.x = p.x; dragging.y = p.y; dragging.vx = 0; dragging.vy = 0; alpha = .55; return; }}
        if (isPanning) {{ pan.x += e.clientX - last.x; pan.y += e.clientY - last.y; last = {{x:e.clientX,y:e.clientY}}; return; }}
        hovered = hit(e.clientX, e.clientY);
      }});
      canvas.addEventListener('mousedown', e => {{
        const n = hit(e.clientX, e.clientY);
        if (n) {{ dragging = n; canvas.classList.add('dragging'); }}
        else {{ isPanning = true; last = {{x:e.clientX,y:e.clientY}}; }}
      }});
      window.addEventListener('mouseup', () => {{ dragging = null; isPanning = false; canvas.classList.remove('dragging'); }});
      canvas.addEventListener('click', e => {{ const n = hit(e.clientX, e.clientY); openPanel(n); }});
      canvas.addEventListener('wheel', e => {{
        e.preventDefault();
        const delta = e.deltaY > 0 ? .92 : 1.08;
        zoom = Math.max(.35, Math.min(2.8, zoom * delta));
      }}, {{ passive: false }});
      document.getElementById('kg-close').onclick = () => openPanel(null);
      document.getElementById('kg-labels').onchange = e => showLabels = e.target.checked;
      document.getElementById('kg-refresh').onclick = () => {{ alpha = 1; nodes.forEach(n => {{ n.vx += (Math.random()-.5)*6; n.vy += (Math.random()-.5)*6; }}); }};
      document.getElementById('kg-reset').onclick = () => {{ zoom = 1; pan = {{x:0,y:0}}; openPanel(null); }};
      document.getElementById('kg-fit').onclick = () => {{ zoom = .92; pan = {{x:0,y:0}}; }};
      document.getElementById('kg-add').onclick = () => {{
        const parent = nodes[Math.floor(Math.random() * nodes.length)];
        const id = 'mock-' + Math.random().toString(16).slice(2, 7);
        const node = {{ id, label: 'Mock Node ' + nodes.length, code: 'MN', type: 'concept', description: 'Simulated temporary graph node.', importance: .45, confidence: .74, color: '#06b6d4', tags: ['mock'], metadata: {{ status: 'simulated' }}, x: parent.x + 30, y: parent.y + 30, vx: 0, vy: 0, radius: 24 }};
        nodes.push(node); byId.set(id, node); links.push({{ source: parent, target: node, label: 'SIMULATES', strength: .55 }});
        alpha = 1; renderLegend();
      }};
      window.addEventListener('resize', resize);
      resize(); renderLegend(); draw();
    }})();
    </script>
    """
    encoded = base64.b64encode(component.encode("utf-8")).decode("ascii")
    st.iframe(f"data:text/html;base64,{encoded}", height=540, width="stretch")


def render_agent_roster() -> None:
    active_agents = active_agent_ids()
    cards = []
    for agent_id in ["market", "strategy", "risk", "compliance", "chart", "execution", "report"]:
        spec = AGENT_SPECS[agent_id]
        state = t("active") if agent_id in active_agents else t("standby")
        exec_class = " exec" if agent_id in {"risk", "execution", "compliance"} else ""
        cards.append(
            f"""
          <div class="agent-card">
            <div class="agent-head">
              <div class="agent-icon{exec_class}">{html.escape(spec["code"])}</div>
              <div>
                <div class="agent-name">{html.escape(agent_name(agent_id))}</div>
                <div class="agent-role">{html.escape(agent_role(agent_id))}</div>
              </div>
            </div>
            <div class="agent-status-row">
              <span class="agent-chip{exec_class}">{html.escape(state)}</span>
              <span>{html.escape(t("agent_team"))}</span>
            </div>
            <div class="agent-bubble">{readable_agent_bubble(agent_id)}</div>
          </div>
            """
        )

    st.markdown(
        f"""
        <div class="agent-stage">
          {''.join(cards)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def candles_frame_from_result(result: dict[str, Any] | None) -> pd.DataFrame:
    if not result or not result.get("ok"):
        return pd.DataFrame()
    candles = ((result.get("data") or {}).get("ohlcv") or [])
    if not candles:
        return pd.DataFrame()

    frame = pd.DataFrame(candles)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["utc_time"] = frame["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    frame["local_time"] = frame["timestamp"].dt.tz_convert(LOCAL_TZ).dt.strftime("%Y-%m-%d %H:%M:%S MYT")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
    frame["ma5"] = frame["close"].rolling(5).mean()
    frame["ma20"] = frame["close"].rolling(20).mean()
    return frame.reset_index(drop=True)


def normalize_close(frame: pd.DataFrame) -> pd.Series:
    first = frame["close"].dropna().iloc[0]
    if first == 0:
        return frame["close"]
    return frame["close"] / first * 100


def chart_config() -> dict[str, Any]:
    return {
        "displaylogo": False,
        "responsive": True,
        "scrollZoom": True,
        "modeBarButtonsToAdd": [
            "drawline",
            "drawopenpath",
            "drawclosedpath",
            "drawcircle",
            "drawrect",
            "eraseshape",
        ],
        "toImageButtonOptions": {
            "format": "png",
            "filename": "deriv-trading-chart",
            "height": 900,
            "width": 1600,
            "scale": 2,
        },
    }


def render_chart_stats(frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    latest = frame.iloc[-1]
    first_close = float(frame.iloc[0]["close"])
    latest_close = float(latest["close"])
    change = latest_close - first_close
    change_pct = (change / first_close * 100) if first_close else 0
    high = float(frame["high"].max())
    low = float(frame["low"].min())

    cols = st.columns(4)
    stat_items = [
        ("Latest close", f"{latest_close:.5g}"),
        ("Change", f"{change:+.5g} ({change_pct:+.2f}%)"),
        ("Range high", f"{high:.5g}"),
        ("Range low", f"{low:.5g}"),
    ]
    for col, (label, value) in zip(cols, stat_items, strict=True):
        col.markdown(
            f'<div class="chart-stat"><span>{label}</span><strong>{value}</strong></div>',
            unsafe_allow_html=True,
        )


def render_measurement(frame: pd.DataFrame) -> None:
    if len(frame) < 2:
        return

    st.markdown(f"#### {t('measure')}")
    labels = [f"{idx} · {row.timestamp.strftime('%m-%d %H:%M')} · close {row.close:.5g}" for idx, row in frame.iterrows()]
    col_a, col_b = st.columns(2)
    start_label = col_a.selectbox(t("start_candle"), labels, index=max(len(labels) - 12, 0))
    end_label = col_b.selectbox(t("end_candle"), labels, index=len(labels) - 1)
    start_idx = int(start_label.split(" · ", 1)[0])
    end_idx = int(end_label.split(" · ", 1)[0])
    if start_idx == end_idx:
        st.caption(t("measure_hint"))
        return
    if start_idx > end_idx:
        start_idx, end_idx = end_idx, start_idx

    start = frame.iloc[start_idx]
    end = frame.iloc[end_idx]
    delta_price = float(end["close"] - start["close"])
    delta_pct = delta_price / float(start["close"]) * 100 if float(start["close"]) else 0
    elapsed = end["timestamp"] - start["timestamp"]
    bars = end_idx - start_idx
    range_high = float(frame.iloc[start_idx : end_idx + 1]["high"].max())
    range_low = float(frame.iloc[start_idx : end_idx + 1]["low"].min())

    cols = st.columns(4)
    cols[0].metric(t("bar_count"), bars)
    cols[1].metric(t("time_span"), str(elapsed))
    cols[2].metric(t("close_delta"), f"{delta_price:+.5g}", f"{delta_pct:+.2f}%")
    cols[3].metric(t("range_amplitude"), f"{range_high - range_low:.5g}")


def fetch_compare_candles(symbol: str, granularity: int, count: int) -> dict[str, Any]:
    return call_deriv_tool(
        "get_historical_candles",
        get_historical_candles(symbol, granularity, count),
        {"symbol": symbol, "granularity": granularity, "count": count},
    )


def fetch_and_store_candles(symbol: str, granularity: int, count: int, source: str) -> dict[str, Any]:
    result = fetch_compare_candles(symbol, granularity, count)
    add_chart_snapshot(result, source=source)
    return result


def render_trading_chart_workbench(result: dict[str, Any]) -> None:
    frame = candles_frame_from_result(result)
    if frame.empty:
        st.info(t("chart_empty_info"))
        return

    data = result.get("data") or {}
    symbol = data.get("symbol", DEFAULT_SYMBOL)
    granularity = int(data.get("granularity") or DEFAULT_GRANULARITY)
    count = int(data.get("returned_count") or len(frame))

    st.markdown(
        f"""
        <div class="chart-workbench">
          <strong>{html.escape(t("chart_workbench"))}</strong>
          <div class="chart-toolbar-note">
            {html.escape(t("chart_note"))}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    control_a, control_b, control_c = st.columns([0.32, 0.34, 0.34])
    st.session_state.chart_height = control_a.slider(
        t("chart_height"),
        min_value=420,
        max_value=950,
        value=int(st.session_state.chart_height),
        step=40,
    )
    compare_enabled = control_b.toggle(t("compare_trend"), value=bool(st.session_state.compare_result))
    st.session_state.compare_symbol = control_c.text_input(
        t("compare_symbol"),
        value=st.session_state.compare_symbol,
        placeholder=t("compare_placeholder"),
    )

    refresh_cols = st.columns([0.25, 0.25, 0.5])
    if refresh_cols[0].button(t("refresh_current"), width="stretch"):
        fetch_and_store_candles(symbol, granularity, count, source="manual_refresh")
        st.rerun()
    if refresh_cols[1].button(t("refresh_compare"), width="stretch"):
        st.session_state.compare_result = fetch_compare_candles(
            st.session_state.compare_symbol.strip() or "R_75",
            granularity,
            count,
        )
        st.rerun()
    if not compare_enabled:
        st.session_state.compare_result = None

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=frame["timestamp"],
            open=frame["open"],
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            increasing_line_color="#007f73",
            decreasing_line_color="#be3434",
            increasing_fillcolor="#007f73",
            decreasing_fillcolor="#be3434",
            name=symbol,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=frame["timestamp"],
            y=frame["ma5"],
            mode="lines",
            line=dict(color="#d89b24", width=1.5),
            name="MA5",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=frame["timestamp"],
            y=frame["ma20"],
            mode="lines",
            line=dict(color="#2457c5", width=1.5),
            name="MA20",
        )
    )

    compare_frame = candles_frame_from_result(st.session_state.compare_result)
    if compare_enabled and not compare_frame.empty:
        compare_symbol = ((st.session_state.compare_result.get("data") or {}).get("symbol") or "Compare")
        fig.add_trace(
            go.Scatter(
                x=compare_frame["timestamp"],
                y=normalize_close(compare_frame),
                yaxis="y2",
                mode="lines",
                line=dict(color="#7a4bd1", width=2),
                name=f"{compare_symbol} normalized",
            )
        )

    latest_close = float(frame.iloc[-1]["close"])
    fig.add_hline(
        y=latest_close,
        line_width=1,
        line_dash="dot",
        line_color="#007f73",
        annotation_text=f"Last {latest_close:.5g}",
        annotation_position="right",
    )
    fig.update_layout(
        title=f"{symbol} · {t('chart_title_suffix')} · granularity={granularity}s · candles={len(frame)}",
        height=int(st.session_state.chart_height),
        margin=dict(l=14, r=14, t=54, b=28),
        paper_bgcolor="#101a17",
        plot_bgcolor="#08110f",
        font=dict(color="#e8f2ed"),
        hovermode="x unified",
        dragmode="pan",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(
            rangeslider=dict(visible=True),
            gridcolor="#223831",
            zerolinecolor="#223831",
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            rangeselector=dict(
                buttons=[
                    dict(count=15, label="15", step="minute", stepmode="backward"),
                    dict(count=1, label="1H", step="hour", stepmode="backward"),
                    dict(count=4, label="4H", step="hour", stepmode="backward"),
                    dict(step="all", label="All"),
                ]
            ),
        ),
        yaxis=dict(
            title=symbol,
            gridcolor="#223831",
            zerolinecolor="#223831",
            showspikes=True,
            spikemode="across",
            fixedrange=False,
        ),
        yaxis2=dict(
            title="Compare normalized",
            overlaying="y",
            side="right",
            showgrid=False,
            visible=compare_enabled and not compare_frame.empty,
        ),
    )
    st.plotly_chart(fig, width="stretch", config=chart_config())

    render_chart_stats(frame)

    with st.expander(t("measure_data"), expanded=True):
        render_measurement(frame)
        st.markdown(f"#### {t('full_ohlcv')}")
        st.dataframe(
            frame[
                ["utc_time", "local_time", "open", "high", "low", "close", "volume", "ma5", "ma20"]
            ],
            width="stretch",
            height=320,
        )
        st.download_button(
            t("download_ohlcv"),
            data=frame.to_csv(index=False).encode("utf-8"),
            file_name=f"{symbol}-ohlcv.csv",
            mime="text/csv",
            width="stretch",
        )


def render_last_artifacts() -> None:
    if st.session_state.last_trade_receipt and st.session_state.last_trade_receipt.get("ok"):
        receipt = ((st.session_state.last_trade_receipt.get("data") or {}).get("receipt") or {})
        st.success("模拟交易执行成功" if current_lang() == "zh" else "Demo trade executed")
        st.markdown(
            f'<div class="success-badge">{html.escape(t("success_badge"))}</div>',
            unsafe_allow_html=True,
        )
        st.json(receipt)

    snapshots = st.session_state.chart_snapshots
    if snapshots:
        st.markdown(f"#### {t('chart_snapshots')}")
        tabs = st.tabs(
            [
                f"{item.get('symbol')} · {item.get('granularity')}s · {item.get('created_at', '')[11:19]}"
                for item in snapshots
            ]
        )
        for tab, item in zip(tabs, snapshots, strict=False):
            with tab:
                st.caption(f"{t('snapshot_time')}: {item.get('created_at')} · source={item.get('source')}")
                render_trading_chart_workbench(item["result"])
    elif st.session_state.last_candles and st.session_state.last_candles.get("ok"):
        render_trading_chart_workbench(st.session_state.last_candles)
    else:
        with st.container(border=True):
            st.subheader(t("chart_workbench"))
            st.caption(t("no_chart_snapshots"))
            if st.button(t("load_default"), type="primary", width="stretch"):
                fetch_and_store_candles("R_100", 60, 120, source="default_loader")
                st.rerun()

    if st.session_state.last_tick and st.session_state.last_tick.get("ok"):
        tick = ((st.session_state.last_tick.get("data") or {}).get("tick") or {})
        with st.container(border=True):
            st.subheader(t("latest_tick"))
            st.metric(tick.get("symbol", DEFAULT_SYMBOL), tick.get("quote"))
            st.caption(tick.get("timestamp"))


def direct_tool_for_agent(agent_id: str) -> str:
    return {
        "market": "assign_task_to_market_agent",
        "strategy": "assign_task_to_strategy_agent",
        "risk": "assign_task_to_risk_agent",
        "compliance": "assign_task_to_compliance_agent",
        "chart": "assign_task_to_chart_agent",
        "execution": "assign_task_to_execution_agent",
        "report": "assign_task_to_report_agent",
    }[agent_id]


def direct_arguments(agent_id: str, task: str) -> dict[str, Any]:
    symbol = extract_symbol(task)
    amount = extract_amount(task)
    contract_type = extract_contract_type(task) or "CALL"
    base: dict[str, Any] = {"task": task, "symbol": symbol}
    if agent_id == "market":
        base.update(
            {
                "tick_count": extract_count(task) if extract_count(task) > 0 else 10,
                "granularity": extract_granularity(task),
                "candle_count": extract_count(task) if extract_count(task) > 0 else 60,
                "analysis_goal": "consecutive_down" if "跌" in task else "tick_trend",
            }
        )
    elif agent_id == "chart":
        base.update(
            {
                "granularity": extract_granularity(task),
                "count": extract_count(task) if extract_count(task) > 0 else 120,
            }
        )
    elif agent_id == "risk":
        base["amount"] = amount
    elif agent_id == "compliance":
        base = {"task": task, "amount": amount, "contract_type": contract_type}
    elif agent_id == "execution":
        base.update(
            {
                "amount": amount,
                "contract_type": contract_type,
                "duration": extract_duration(task) or 5,
                "duration_unit": extract_duration_unit(task),
                "risk_note": "老板直派执行任务，请按模拟盘安全边界执行。",
            }
        )
    return base


def render_direct_dispatch() -> None:
    st.markdown(f"#### {t('direct_dispatch')}")
    agent_options = ["market", "strategy", "risk", "compliance", "chart", "execution", "report"]
    col_agent, col_button = st.columns([0.68, 0.32])
    selected_agent = col_agent.selectbox(
        t("direct_agent"),
        agent_options,
        format_func=agent_name,
        key="direct_agent_select",
        label_visibility="collapsed",
    )
    task_key = f"direct_task_{st.session_state.direct_prompt_nonce}"
    direct_task = st.text_area(
        t("direct_task"),
        key=task_key,
        height=86,
        placeholder=t("direct_task_placeholder"),
        label_visibility="collapsed",
    )
    dispatch_clicked = col_button.button(t("dispatch"), type="primary", width="stretch")
    if not dispatch_clicked:
        return
    task = direct_task.strip()
    if not task:
        st.warning(t("empty_command"))
        return
    events: list[AgentEvent] = []
    dispatch_line = (
        f"老板直派 {agent_name(selected_agent)}：{task}"
        if current_lang() == "zh"
        else f"Boss directly assigned {agent_name(selected_agent)}: {task}"
    )
    append_team_event(events, "用户", "经理", dispatch_line, st.write)
    result = manager_tool_dispatch(
        direct_tool_for_agent(selected_agent),
        direct_arguments(selected_agent, task),
        events,
        st.write,
    )
    done_line = (
        f"{agent_name(selected_agent)} 已完成直派任务。"
        if current_lang() == "zh"
        else f"{agent_name(selected_agent)} completed the direct task."
    )
    append_team_event(events, "经理", "用户", done_line, st.write)
    publish_team_log(events, [json.dumps(result, ensure_ascii=False, indent=2, default=str)])
    st.success(t("direct_done"))
    st.session_state.direct_prompt_nonce += 1


def render_sync_bus() -> None:
    st.markdown(f"#### {t('sync_bus')}")
    st.caption(t("sync_bus_hint"))
    cols = st.columns(4)
    cols[0].metric(t("sync_version"), st.session_state.get("sync_version", 0))
    cols[1].metric("Agent Events", len(st.session_state.get("team_events", [])))
    cols[2].metric("API Calls", len(st.session_state.get("api_trace", [])))
    cols[3].metric("Chart Snapshots", len(st.session_state.get("chart_snapshots", [])))
    st.code(format_runtime_events(18), language="text")
    with st.expander(t("api_trace"), expanded=False):
        api_rows = st.session_state.get("api_trace", [])[-20:]
        if api_rows:
            st.dataframe(api_rows, width="stretch", height=240)
        else:
            st.caption("No API calls yet." if current_lang() == "en" else "还没有 API 调用。")


def render_chat() -> None:
    with st.container(border=True):
        st.subheader(t("chat_title"))
        st.caption(t("chat_caption"))

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        render_direct_dispatch()

        st.markdown(
            f"""
            <div class="command-panel">
              <div class="command-title">{html.escape(t("command_title"))}</div>
              <div class="command-hint">{html.escape(t("command_hint"))}</div>
              <div class="example-strip">
                <span class="example-pill">{html.escape(t("example_tick"))}</span>
                <span class="example-pill">{html.escape(t("example_candles"))}</span>
                <span class="example-pill">{html.escape(t("example_trade"))}</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        input_key = f"command_input_{st.session_state.prompt_nonce}"
        draft = st.text_area(
            t("command_title"),
            key=input_key,
            height=112,
            placeholder=t("chat_placeholder"),
            label_visibility="collapsed",
        )
        send_col, clear_col, note_col = st.columns([0.3, 0.22, 0.48])
        send_clicked = send_col.button(t("send"), type="primary", width="stretch")
        clear_clicked = clear_col.button(t("clear_input_short"), width="stretch")
        note_col.markdown(
            f'<div class="send-note">{html.escape(t("send_note"))}</div>',
            unsafe_allow_html=True,
        )

        st.markdown(f"#### {t('agent_log')}")
        st.code(st.session_state.agent_execution_log, language="text")
        render_sync_bus()
        st.download_button(
            t("download_log"),
            data=st.session_state.agent_execution_log,
            file_name=f"deriv-agent-log-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt",
            mime="text/plain",
            width="stretch",
        )

        if clear_clicked:
            st.session_state.prompt_nonce += 1
            st.rerun()

        if not send_clicked:
            return

        prompt = draft.strip()
        if not prompt:
            st.warning(t("empty_command"))
            return

        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            live_slot = st.empty()

            def live_writer(line: str) -> None:
                st.write(line)
                live_slot.code(format_runtime_events(22), language="text")

            with st.status(t("team_processing"), expanded=True) as status:
                team_result = run_hierarchical_trading_team(prompt, writer=live_writer)
                if team_result.ok:
                    status.update(label=t("team_done"), state="complete", expanded=True)
                else:
                    status.update(label=t("team_blocked"), state="error", expanded=True)

            with st.expander(t("structured_result"), expanded=False):
                st.json(
                    {
                        "market_report": team_result.market_report,
                        "execution_report": team_result.execution_report,
                        "events": [event.line() for event in team_result.events],
                    }
                )

            answer = team_result.final_answer
            rendered = st.write_stream(stream_text(answer))
            st.session_state.messages.append({"role": "assistant", "content": rendered})
            save_team_run(prompt, team_result)

        st.session_state.prompt_nonce += 1


def main() -> None:
    init_state()
    configure_page()
    render_sidebar()
    render_header()

    left, right = st.columns([0.36, 0.64], gap="large")
    with left:
        render_chat()
    with right:
        render_swarm_graph()
        render_agent_roster()
        st.markdown(f"### {t('live_results')}")
        st.markdown(f'<p class="small-muted">{html.escape(t("results_hint"))}</p>', unsafe_allow_html=True)
        render_last_artifacts()


if __name__ == "__main__":
    main()
