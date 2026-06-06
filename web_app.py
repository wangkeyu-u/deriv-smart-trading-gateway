"""Streamlit web interface for the Deriv Smart Trading Gateway.

Run:
    streamlit run web_app.py
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import html
import operator
import json
import math
import re
import sqlite3
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable, Generator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from advisor_evaluation import (
    advisor_entry_price,
    advisor_evaluation_ready,
    advisor_horizon_readiness,
    evaluate_advisor_horizons,
    evaluate_advisor_outcome,
    future_closes_after_created_at,
    summarize_advisor_evaluations,
    summarize_advisor_performance,
)
from budget_guard import BudgetLimits, budget_guard_check
from micro_trading import MicroTradeConfig, analyze_micro_trade, normalize_price_frame
from paper_trading import CircuitBreakerConfig, backtest_micro_strategy
from server import (
    check_account_status,
    close_open_contract,
    execute_simulated_trade,
    get_open_contract_status,
    get_historical_candles,
    get_market_ticks,
    mask_secret,
)


Provider = Literal["本地规则", "OpenAI", "DeepSeek", "Anthropic", "OpenAI-Compatible"]
Action = Literal["get_market_ticks", "get_historical_candles", "execute_simulated_trade", "chat"]

DEFAULT_SYMBOL = "R_100"
DEFAULT_GRANULARITY = 60
DEFAULT_COUNT = 60
FRESHNESS_LIMITS_SECONDS = {
    "tick": 15,
    "chart": 180,
    "advisor": 300,
}
COMMON_DERIV_SYMBOLS = [
    "R_10",
    "R_25",
    "R_50",
    "R_75",
    "R_100",
    "1HZ10V",
    "1HZ25V",
    "1HZ50V",
    "1HZ75V",
    "1HZ100V",
    "BOOM500",
    "BOOM1000",
    "CRASH500",
    "CRASH1000",
    "JD10",
    "JD25",
    "JD50",
    "JD75",
    "JD100",
    "frxEURUSD",
    "frxGBPUSD",
    "frxUSDJPY",
]
CHART_GRANULARITY_OPTIONS = [60, 120, 300, 900, 1800, 3600]
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "local_data"
DB_PATH = DATA_DIR / "gateway.sqlite3"
AGENT_PROMPTS_PATH = APP_DIR / "agent_prompts.json"
LOCAL_TZ = ZoneInfo("Asia/Kuala_Lumpur")

I18N = {
    "zh": {
        "sidebar_title": "Deriv Gateway",
        "sidebar_caption": "多智能体交易终端",
        "language": "语言",
        "security": "安全密钥配置",
        "execution_safety": "交易安全闸门",
        "require_trade_confirmation": "下单前需要人工确认",
        "confirm_next_trade": "我确认下一笔模拟盘订单",
        "allow_live_execution": "允许 live 账户执行交易",
        "pending_trade": "待确认交易",
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
        "no_chart_snapshots": "还没有图表快照。请选择市场、周期和K线数量后加载。",
        "snapshot_time": "生成时间",
        "chart_loader_title": "加载市场图表",
        "chart_loader_caption": "不用写命令，直接选择市场、周期和K线数量。",
        "chart_symbol_select": "选择市场",
        "chart_custom_symbol": "自定义 Symbol（可选）",
        "chart_custom_placeholder": "例如 frxEURUSD / BOOM1000 / R_75",
        "chart_granularity": "K线周期",
        "chart_candle_count": "K线数量",
        "chart_load_selected": "加载所选图表",
        "chart_loaded": "图表已加载",
        "chart_load_failed": "图表加载失败",
        "sync_bus": "实时同步总线",
        "sync_bus_hint": "API 调用、Agent 事件、图谱状态、图表快照都写入这里。",
        "api_trace": "API 调用 Trace",
        "sync_version": "同步版本",
        "chat_title": "交易经理指令台",
        "chat_caption": "输入自然语言目标；经理用大模型决策派活，每个子 Agent 会用自己的 prompt 和模型 Key 产出判断。",
        "command_title": "交易指令工作台",
        "command_hint": "Enter 只用于中文输入法确认或换行；点击发送按钮才会提交。",
        "send": "发送指令",
        "clear_input": "清空输入",
        "clear_input_short": "清空",
        "send_note": "不会因为 Enter 自动发送，适合中文输入法选词。",
        "agent_log": "智能体自动执行日志",
        "results": "实时交易工作台",
        "results_hint": "K 线图、订单回执、子 Agent 状态和最新 tick 会在这里显示。",
        "load_default": "加载所选图表",
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
        "no_candles": "还没有 K 线数据。可以通过聊天指令生成，也可以在图表页选择市场后加载。",
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
        "chart_empty_info": "没有拿到可绘制的 K 线数据。请换一个市场、周期或减少 K 线数量后重试。",
        "chart_title_suffix": "K 线交易图",
        "chart_advisor_overlay": "谋士参考",
        "local_provider_label": "本地规则",
        "example_tick": "查 R_100 最新价",
        "example_candles": "画 R_100 最近 120 根 1分钟K线",
        "example_trade": "10 美金看涨 · 5 ticks",
        "advisor_council": "老板谋士室",
        "advisor_caption": "多个谋士在限时内读取行情与网页信息，快速讨论后给老板一个可执行倾向。只做决策建议，不自动下单。",
        "advisor_question": "请谋士团分析什么？",
        "advisor_placeholder": "例如：R_100 接下来 5-10 分钟该等还是做多？请结合最新行情和网页消息给我快速结论。",
        "advisor_time_budget": "限时预算（秒）",
        "advisor_web_toggle": "允许联网找资料",
        "advisor_symbol": "分析 Symbol",
        "advisor_start": "召集谋士",
        "advisor_empty": "请输入要谋士团分析的问题。",
        "advisor_processing": "谋士团正在限时讨论...",
        "advisor_done": "谋士团已给出结论",
        "advisor_result": "谋士结论",
        "advisor_sources": "网页来源",
        "advisor_no_sources": "本轮没有抓到可用网页来源，结论主要来自行情与内部规则。",
        "advisor_transcript": "谋士讨论纪要",
        "advisor_download": "下载谋士报告 JSON",
        "advisor_consensus": "一致结论",
        "advisor_confidence": "置信度",
        "advisor_elapsed": "耗时",
        "advisor_disclaimer": "谋士结论不会绕过交易安全闸门；下单仍需走执行交易员和人工确认。",
        "advisor_evaluation": "谋士评估",
        "advisor_evaluation_caption": "用当前最新价和 1m/5m/10m K 线窗口复盘最近谋士判断，只做纸面评估，不代表真实成交。",
        "advisor_entry_price": "入场参考价",
        "advisor_exit_price": "复盘价",
        "advisor_direction_accuracy": "方向准确率",
        "advisor_paper_return": "纸面收益",
        "advisor_mark_recent": "复盘最近谋士判断",
        "advisor_no_evaluations": "还没有可评估的谋士记录。",
        "advisor_outcome": "结果",
        "advisor_horizon_scores": "多窗口评分",
        "workspace": "工作台",
        "page_advisor": "谋士室",
        "page_micro": "小笔策略",
        "page_trading": "交易台",
        "page_charts": "图表",
        "page_monitor": "监控",
        "page_advisor_caption": "限时谋士讨论、网页/行情分析和多窗口纸面复盘。",
        "page_micro_caption": "小额频繁策略、预算闸门、paper trading 回测和熔断器。",
        "page_trading_caption": "交易经理调度执行团队，处理自然语言交易任务和人工确认。",
        "page_charts_caption": "K 线快照、对比走势、测量和最新 Tick。",
        "page_monitor_caption": "Agent 图谱、角色状态、API trace 和同步总线。",
        "status_symbol": "Symbol",
        "status_advisor": "谋士结论",
        "status_entry": "入场价",
        "status_freshness": "数据时效",
        "status_api_calls": "API 调用",
        "status_sync": "同步",
        "status_pending": "待确认",
        "status_none": "无",
        "status_yes": "有",
        "advisor_performance": "谋士表现汇总",
        "safety_gate_panel": "执行安全闸门",
        "safety_token": "Token",
        "safety_confirmation": "人工确认",
        "safety_live": "Live 执行",
        "safety_pending_order": "待确认订单",
        "safety_freshness": "数据时效",
        "safety_ready": "就绪",
        "safety_blocked": "阻断",
        "safety_required": "需要确认",
        "safety_disabled": "关闭",
        "safety_enabled": "开启",
        "pending_action": "动作",
        "pending_direction": "方向",
        "pending_amount": "金额",
        "pending_duration": "时长",
        "pending_advisor_alignment": "谋士一致性",
        "pending_freshness": "数据时效",
        "pending_flags": "风险提示",
        "pending_raw_payload": "原始参数",
        "advisor_trade_draft": "生成交易草稿",
        "advisor_trade_draft_caption": "只生成待确认交易，不会自动下单。",
        "advisor_trade_amount": "草稿金额",
        "advisor_trade_duration": "草稿时长",
        "advisor_trade_created": "已生成待确认交易草稿，请到交易台/侧边栏确认。",
        "advisor_trade_wait_blocked": "当前谋士结论是 WAIT，不生成交易草稿。",
        "audit_export": "审计导出",
        "audit_export_caption": "导出当前决策链状态，不包含 API Token。",
        "download_audit": "下载审计 JSON",
        "system_health": "系统健康",
        "system_health_caption": "本地运行状态检查，不触发网络交易调用。",
        "health_ready": "正常",
        "health_attention": "需关注",
        "health_db": "本地数据库",
        "health_langgraph": "LangGraph",
        "health_token": "Token",
        "health_pending": "待确认",
        "micro_strategy": "小笔频繁策略",
        "micro_strategy_caption": "独立策略实验室：只做分析、回测和预算检查，不影响普通交易台。",
        "micro_goal": "策略目标",
        "micro_symbol": "资产 / Symbol",
        "micro_asset_kind": "资产类型",
        "micro_prices": "近期收盘价",
        "micro_data_source": "数据来源",
        "micro_source_live": "Deriv 最新K线",
        "micro_source_manual": "手动输入收盘价",
        "micro_live_count": "实时K线数量",
        "micro_live_granularity": "实时K线周期",
        "micro_budget": "小笔预算",
        "micro_amount": "单次金额",
        "micro_daily_budget": "日预算",
        "micro_total_budget": "总预算",
        "micro_spent_today": "今日已用",
        "micro_spent_total": "总已用",
        "micro_circuit": "熔断器",
        "micro_max_losses": "连续亏损上限",
        "micro_max_loss_amount": "最大亏损金额",
        "micro_max_drawdown": "最大回撤 %",
        "micro_max_trades": "最大纸面交易数",
        "micro_run": "运行分析和回测",
        "micro_decision": "当前信号",
        "micro_operator_brief": "员工视角结论",
        "micro_operator_recommendation": "行动建议",
        "micro_trade_direction": "观察方向",
        "micro_data_quality": "数据可信度",
        "micro_paper_return": "纸面收益",
        "micro_risk_brief": "风险与预算",
        "micro_evidence": "信号证据",
        "micro_next_steps": "下一步",
        "micro_trade_log": "回测明细",
        "micro_backtest": "纸面回测",
        "micro_no_trade": "当前预算或熔断条件不允许交易。",
        "micro_recent_runs": "最近小笔策略记录",
        "micro_saved": "已保存本轮小笔策略记录",
        "chart_data_status": "图表数据状态",
        "chart_last_candle": "最新 K 线",
        "chart_data_age": "数据年龄",
        "chart_time_zone": "时间显示",
        "chart_local_time_note": "图表横轴显示本地时间 MYT；表格同时保留 UTC 和 MYT。",
        "chart_stale": "可能过期",
        "chart_fresh": "新鲜",
        "chart_refresh_hint": "如果最新 K 线时间落后，请点击刷新当前 K 线。",
        "sync_test_status": "同步测试状态",
    },
    "en": {
        "sidebar_title": "Deriv Gateway",
        "sidebar_caption": "Multi-agent trading terminal",
        "language": "Language",
        "security": "Secure Credentials",
        "execution_safety": "Execution Safety Gate",
        "require_trade_confirmation": "Require human confirmation before orders",
        "confirm_next_trade": "I confirm the next demo order",
        "allow_live_execution": "Allow live account execution",
        "pending_trade": "Pending Trade",
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
        "no_chart_snapshots": "No chart snapshots yet. Choose a market, timeframe, and candle count to load one.",
        "snapshot_time": "Generated",
        "chart_loader_title": "Load Market Chart",
        "chart_loader_caption": "No command needed. Choose the market, timeframe, and candle count.",
        "chart_symbol_select": "Market",
        "chart_custom_symbol": "Custom Symbol (optional)",
        "chart_custom_placeholder": "Example: frxEURUSD / BOOM1000 / R_75",
        "chart_granularity": "Candle Timeframe",
        "chart_candle_count": "Candle Count",
        "chart_load_selected": "Load Selected Chart",
        "chart_loaded": "Chart loaded",
        "chart_load_failed": "Chart load failed",
        "sync_bus": "Live Sync Bus",
        "sync_bus_hint": "API calls, agent events, graph state, and chart snapshots all write here.",
        "api_trace": "API Trace",
        "sync_version": "Sync Version",
        "chat_title": "Trading Manager Console",
        "chat_caption": "Enter a natural-language goal; the manager uses the model to delegate work, and each sub-agent uses its own prompt plus your model key for judgment.",
        "command_title": "Order Command Pad",
        "command_hint": "Enter only confirms IME text or inserts a new line; click Send to submit.",
        "send": "Send Order",
        "clear_input": "Clear Input",
        "clear_input_short": "Clear",
        "send_note": "Enter will not auto-send, so IME composition is safe.",
        "agent_log": "Agent Execution Log",
        "results": "Live Trading Workbench",
        "results_hint": "Candles, receipts, sub-agent state, and latest ticks appear here.",
        "load_default": "Load Selected Chart",
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
        "no_candles": "No candle data yet. Ask in chat or choose a market on the Charts page.",
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
        "chart_empty_info": "No drawable candle data was returned. Try another market, timeframe, or a smaller candle count.",
        "chart_title_suffix": "Candlestick Trading Chart",
        "chart_advisor_overlay": "Advisor Reference",
        "local_provider_label": "Local Rules",
        "example_tick": "R_100 latest tick",
        "example_candles": "R_100 · 120 candles · 1m",
        "example_trade": "10 USD CALL · 5 ticks",
        "advisor_council": "Boss Advisor Room",
        "advisor_caption": "Several advisors read market data and web context under a strict time budget, then produce one actionable view. Advice only; no automatic orders.",
        "advisor_question": "What should the advisors analyze?",
        "advisor_placeholder": "Example: Should I wait or go long on R_100 over the next 5-10 minutes? Use latest market data and web context.",
        "advisor_time_budget": "Time budget (seconds)",
        "advisor_web_toggle": "Allow web research",
        "advisor_symbol": "Analysis Symbol",
        "advisor_start": "Convene Advisors",
        "advisor_empty": "Please enter an advisor question.",
        "advisor_processing": "Advisors are debating under the time limit...",
        "advisor_done": "Advisor conclusion ready",
        "advisor_result": "Advisor Result",
        "advisor_sources": "Web Sources",
        "advisor_no_sources": "No usable web sources were found. This run mainly used market data and local rules.",
        "advisor_transcript": "Advisor Transcript",
        "advisor_download": "Download Advisor JSON",
        "advisor_consensus": "Consensus",
        "advisor_confidence": "Confidence",
        "advisor_elapsed": "Elapsed",
        "advisor_disclaimer": "Advisor output does not bypass the execution safety gate; orders still require the execution agent and human confirmation.",
        "advisor_evaluation": "Advisor Evaluation",
        "advisor_evaluation_caption": "Mark recent advisor calls against the latest price and 1m/5m/10m candle horizons. Paper evaluation only; not real execution.",
        "advisor_entry_price": "Entry Reference",
        "advisor_exit_price": "Mark Price",
        "advisor_direction_accuracy": "Direction Accuracy",
        "advisor_paper_return": "Paper Return",
        "advisor_mark_recent": "Evaluate Recent Advisors",
        "advisor_no_evaluations": "No evaluable advisor records yet.",
        "advisor_outcome": "Outcome",
        "advisor_horizon_scores": "Horizon Scores",
        "workspace": "Workspace",
        "page_advisor": "Advisor Room",
        "page_micro": "Micro Strategy",
        "page_trading": "Trading Desk",
        "page_charts": "Charts",
        "page_monitor": "Monitor",
        "page_advisor_caption": "Time-boxed advisor debate, market/web context, and multi-horizon paper evaluation.",
        "page_micro_caption": "Small-budget frequent strategy, budget guard, paper trading, and circuit breakers.",
        "page_trading_caption": "The trading manager routes natural-language work through the execution team and safety gates.",
        "page_charts_caption": "Candlestick snapshots, comparison overlays, measurement, and latest ticks.",
        "page_monitor_caption": "Agent graph, role state, API traces, and live sync bus.",
        "status_symbol": "Symbol",
        "status_advisor": "Advisor",
        "status_entry": "Entry",
        "status_freshness": "Freshness",
        "status_api_calls": "API Calls",
        "status_sync": "Sync",
        "status_pending": "Pending",
        "status_none": "None",
        "status_yes": "Yes",
        "advisor_performance": "Advisor Performance",
        "safety_gate_panel": "Execution Safety Gate",
        "safety_token": "Token",
        "safety_confirmation": "Human Confirm",
        "safety_live": "Live Execution",
        "safety_pending_order": "Pending Order",
        "safety_freshness": "Data Freshness",
        "safety_ready": "Ready",
        "safety_blocked": "Blocked",
        "safety_required": "Required",
        "safety_disabled": "Disabled",
        "safety_enabled": "Enabled",
        "pending_action": "Action",
        "pending_direction": "Direction",
        "pending_amount": "Amount",
        "pending_duration": "Duration",
        "pending_advisor_alignment": "Advisor Alignment",
        "pending_freshness": "Data Freshness",
        "pending_flags": "Risk Flags",
        "pending_raw_payload": "Raw Payload",
        "advisor_trade_draft": "Create Trade Draft",
        "advisor_trade_draft_caption": "Creates a pending trade only. It does not submit an order.",
        "advisor_trade_amount": "Draft Amount",
        "advisor_trade_duration": "Draft Duration",
        "advisor_trade_created": "Pending trade draft created. Review it in the trading desk/sidebar.",
        "advisor_trade_wait_blocked": "Advisor stance is WAIT, so no trade draft was created.",
        "audit_export": "Audit Export",
        "audit_export_caption": "Export the current decision-chain state. API tokens are not included.",
        "download_audit": "Download Audit JSON",
        "system_health": "System Health",
        "system_health_caption": "Local runtime checks without network trading calls.",
        "health_ready": "Ready",
        "health_attention": "Attention",
        "health_db": "Local DB",
        "health_langgraph": "LangGraph",
        "health_token": "Token",
        "health_pending": "Pending",
        "micro_strategy": "Micro Strategy",
        "micro_strategy_caption": "Standalone strategy lab: analysis, paper trading, and budget checks only. It does not change the main trading desk.",
        "micro_goal": "Strategy Goal",
        "micro_symbol": "Asset / Symbol",
        "micro_asset_kind": "Asset Kind",
        "micro_prices": "Recent Closes",
        "micro_data_source": "Data Source",
        "micro_source_live": "Latest Deriv Candles",
        "micro_source_manual": "Manual Close Input",
        "micro_live_count": "Live Candle Count",
        "micro_live_granularity": "Live Granularity",
        "micro_budget": "Micro Budget",
        "micro_amount": "Trade Amount",
        "micro_daily_budget": "Daily Budget",
        "micro_total_budget": "Total Budget",
        "micro_spent_today": "Spent Today",
        "micro_spent_total": "Spent Total",
        "micro_circuit": "Circuit Breaker",
        "micro_max_losses": "Max Loss Streak",
        "micro_max_loss_amount": "Max Loss Amount",
        "micro_max_drawdown": "Max Drawdown %",
        "micro_max_trades": "Max Paper Trades",
        "micro_run": "Run Analysis & Backtest",
        "micro_decision": "Current Signal",
        "micro_operator_brief": "Operator Brief",
        "micro_operator_recommendation": "Recommendation",
        "micro_trade_direction": "Observed Direction",
        "micro_data_quality": "Data Quality",
        "micro_paper_return": "Paper Return",
        "micro_risk_brief": "Risk And Budget",
        "micro_evidence": "Signal Evidence",
        "micro_next_steps": "Next Steps",
        "micro_trade_log": "Paper Trading Log",
        "micro_backtest": "Paper Trading Backtest",
        "micro_no_trade": "Budget or circuit conditions do not allow a trade.",
        "micro_recent_runs": "Recent Micro Strategy Runs",
        "micro_saved": "Saved this micro strategy run",
        "chart_data_status": "Chart Data Status",
        "chart_last_candle": "Latest Candle",
        "chart_data_age": "Data Age",
        "chart_time_zone": "Time Display",
        "chart_local_time_note": "The chart x-axis uses local MYT time; the table keeps both UTC and MYT.",
        "chart_stale": "Possibly Stale",
        "chart_fresh": "Fresh",
        "chart_refresh_hint": "If the latest candle is behind, refresh the current chart.",
        "sync_test_status": "Sync Test Status",
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

ADVISOR_SPECS: list[dict[str, str]] = [
    {
        "id": "macro",
        "code": "MX",
        "zh_name": "宏观大佬",
        "en_name": "Macro Chair",
        "zh_role": "先看大环境、新闻冲击和风险偏好",
        "en_role": "Reads macro context, news shocks, and risk appetite",
        "color": "#7aa7ff",
    },
    {
        "id": "quant",
        "code": "QX",
        "zh_name": "量化大佬",
        "en_name": "Quant Chair",
        "zh_role": "只认短线动量、均线和最新 Tick",
        "en_role": "Focuses on short-term momentum, moving averages, and ticks",
        "color": "#6ee7f9",
    },
    {
        "id": "flow",
        "code": "FX",
        "zh_name": "盘口大佬",
        "en_name": "Flow Chair",
        "zh_role": "盯节奏、波动和临场执行窗口",
        "en_role": "Watches rhythm, volatility, and execution windows",
        "color": "#00b894",
    },
    {
        "id": "risk",
        "code": "RX",
        "zh_name": "风控大佬",
        "en_name": "Risk Chair",
        "zh_role": "先保命，再谈收益",
        "en_role": "Protects capital before seeking upside",
        "color": "#f5b84b",
    },
    {
        "id": "contrarian",
        "code": "CX",
        "zh_name": "反方谋士",
        "en_name": "Devil's Advocate",
        "zh_role": "专门挑刺，找共识里的漏洞",
        "en_role": "Challenges consensus and hunts for weak assumptions",
        "color": "#c39bff",
    },
]


class AdvisorGraphState(TypedDict, total=False):
    question: str
    symbol: str
    budget: int
    use_web: bool
    language: str
    started_at: float
    writer: Callable[[str], None] | None
    sources: list[dict[str, str]]
    market: dict[str, Any]
    news_signal: dict[str, Any]
    opinions: Annotated[list[dict[str, Any]], operator.add]
    logs: Annotated[list[str], operator.add]
    local_consensus: dict[str, Any]
    consensus: str
    stance: str
    confidence: float
    vote_counts: dict[str, int]
    graph_runtime: str


def default_agent_prompts() -> dict[str, dict[str, str]]:
    return {
        "manager": {
            "name": "交易经理",
            "prompt": "你是交易经理，负责把老板目标拆成行情、策略、风控、合规、执行和报告任务。不要直接下单。",
        },
        "market": {
            "name": "行情分析师",
            "prompt": "你负责读取 Deriv Tick/K 线，判断趋势、连续波动和触发条件。输出要短、准、可审计。",
        },
        "strategy": {
            "name": "策略研究员",
            "prompt": "你负责把交易目标拆成假设、观察窗口、入场条件、退出条件和需要哪些 agent 协同。",
        },
        "risk": {
            "name": "风控官",
            "prompt": "你负责检查 Token、账户、金额、live/demo 边界和最大损失。你的默认立场是先保护本金。",
        },
        "compliance": {
            "name": "合规审查员",
            "prompt": "你负责阻止含糊、缺授权、缺方向、满仓、梭哈或绕过安全闸门的请求。",
        },
        "chart": {
            "name": "图表工程师",
            "prompt": "你负责生成 K 线快照、对比走势、测量窗口和可下载数据。",
        },
        "execution": {
            "name": "执行交易员",
            "prompt": "你是唯一能提交 Deriv 写操作的 agent。必须经过风控、合规和人工确认，不允许绕过安全闸门。",
        },
        "report": {
            "name": "报告员",
            "prompt": "你负责把每轮协作写成时间线、结构化结果、回执和复盘摘要。",
        },
        "advisor.macro": {
            "name": "宏观大佬",
            "prompt": "你先看外部消息、宏观风险偏好和新闻催化。没有明确催化时，不要催促老板追单。",
        },
        "advisor.quant": {
            "name": "量化大佬",
            "prompt": "你只认短线动量、MA5/MA20、最新 Tick 和窗口内涨跌幅。趋势不干净就倾向等待。",
        },
        "advisor.flow": {
            "name": "盘口大佬",
            "prompt": "你盯盘口节奏、波动速度和临场执行窗口。给出方向时必须附带等待确认条件。",
        },
        "advisor.risk": {
            "name": "风控大佬",
            "prompt": "你先保命，再谈收益。外部信息不足、置信度不足或时间过紧时，优先建议 WAIT。",
        },
        "advisor.contrarian": {
            "name": "反方谋士",
            "prompt": "你专门挑战共识，寻找已经被价格吸收、追高杀跌、样本不足和信息滞后的风险。",
        },
        "advisor.chief": {
            "name": "首席谋士",
            "prompt": "你汇总所有谋士观点，只输出一个短线结论：CALL、PUT 或 WAIT；必须包含置信度、执行前提和失效条件。",
        },
    }


def load_agent_prompts() -> dict[str, dict[str, str]]:
    defaults = default_agent_prompts()
    if not AGENT_PROMPTS_PATH.exists():
        return defaults
    try:
        loaded = json.loads(AGENT_PROMPTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    if not isinstance(loaded, dict):
        return defaults
    merged = dict(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict):
            existing = merged.get(str(key), {})
            merged[str(key)] = {
                "name": str(value.get("name") or existing.get("name") or key),
                "prompt": str(value.get("prompt") or existing.get("prompt") or ""),
            }
    return merged


def agent_prompt(agent_id: str) -> str:
    return load_agent_prompts().get(agent_id, {}).get("prompt", "")


def safe_agent_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_").lower()
    return cleaned or "custom"


def advisor_node_name(advisor_id: str) -> str:
    return f"advisor_{safe_agent_id(advisor_id)}"


def advisor_specs() -> list[dict[str, str]]:
    specs = [dict(item) for item in ADVISOR_SPECS]
    existing = {item["id"] for item in specs}
    colors = ["#7aa7ff", "#6ee7f9", "#00b894", "#f5b84b", "#c39bff", "#d8d257"]
    for key, value in load_agent_prompts().items():
        if not key.startswith("advisor.") or key == "advisor.chief":
            continue
        advisor_id = safe_agent_id(key.split(".", 1)[1])
        if advisor_id in existing:
            continue
        name = str(value.get("name") or advisor_id)
        role = str(value.get("prompt") or "")[:44] or "自定义谋士"
        specs.append(
            {
                "id": advisor_id,
                "code": advisor_id[:2].upper().ljust(2, "X"),
                "zh_name": name,
                "en_name": name,
                "zh_role": role,
                "en_role": role,
                "color": colors[len(specs) % len(colors)],
            }
        )
        existing.add(advisor_id)
    return specs


def current_lang() -> str:
    if not in_streamlit_runtime():
        return "zh"
    return st.session_state.get("language", "zh")


def in_streamlit_runtime() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx(suppress_warning=True) is not None
    except Exception:
        return False


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS advisor_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                question TEXT NOT NULL,
                symbol TEXT NOT NULL,
                consensus TEXT NOT NULL,
                confidence REAL NOT NULL,
                elapsed_ms REAL NOT NULL,
                result_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS micro_strategy_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                goal TEXT NOT NULL,
                symbol TEXT NOT NULL,
                asset_kind TEXT NOT NULL,
                action TEXT NOT NULL,
                confidence REAL NOT NULL,
                budget_ok INTEGER NOT NULL,
                trade_count INTEGER NOT NULL,
                total_pnl REAL NOT NULL,
                halted INTEGER NOT NULL,
                run_json TEXT NOT NULL
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


def save_advisor_run(result: dict[str, Any]) -> None:
    init_local_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO advisor_runs (
                created_at, question, symbol, consensus, confidence, elapsed_ms, result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                str(result.get("question") or ""),
                str(result.get("symbol") or DEFAULT_SYMBOL),
                str(result.get("consensus") or ""),
                float(result.get("confidence") or 0),
                float(result.get("elapsed_ms") or 0),
                json.dumps(result, ensure_ascii=False, default=str),
            ),
        )


def load_recent_advisor_runs(limit: int = 3) -> list[dict[str, Any]]:
    init_local_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, created_at, question, symbol, consensus, confidence, elapsed_ms
            FROM advisor_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def load_advisor_run_records(limit: int = 12) -> list[dict[str, Any]]:
    init_local_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, created_at, question, symbol, consensus, confidence, elapsed_ms, result_json
            FROM advisor_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    records: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        try:
            payload = json.loads(str(record.get("result_json") or "{}"))
        except json.JSONDecodeError:
            payload = {}
        record["result"] = payload if isinstance(payload, dict) else {}
        records.append(record)
    return records


def save_micro_strategy_run(
    *,
    goal: str,
    config: MicroTradeConfig,
    decision: dict[str, Any],
    budget_check: dict[str, Any],
    backtest: dict[str, Any],
    operator_brief: dict[str, Any] | None = None,
    data_source: str = "manual",
) -> None:
    init_local_db()
    summary = backtest.get("summary") or {}
    payload = {
        "goal": goal,
        "config": {
            "symbol": config.symbol,
            "asset_kind": config.asset_kind,
            "cadence_seconds": config.cadence_seconds,
            "max_trade_amount": config.max_trade_amount,
            "min_confidence": config.min_confidence,
            "max_volatility_pct": config.max_volatility_pct,
            "fee_bps": config.fee_bps,
            "slippage_bps": config.slippage_bps,
            "cooldown_seconds": config.cooldown_seconds,
            "max_daily_loss_pct": config.max_daily_loss_pct,
        },
        "decision": decision,
        "budget_guard": budget_check,
        "backtest": backtest,
        "operator_brief": operator_brief or {},
        "data_source": data_source,
    }
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO micro_strategy_runs (
                created_at, goal, symbol, asset_kind, action, confidence,
                budget_ok, trade_count, total_pnl, halted, run_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                goal,
                config.symbol,
                config.asset_kind,
                str(decision.get("action") or ""),
                float(decision.get("confidence") or 0),
                1 if budget_check.get("ok") else 0,
                int(summary.get("trade_count") or 0),
                float(summary.get("total_pnl") or 0),
                1 if summary.get("halted") else 0,
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )


def load_recent_micro_strategy_runs(limit: int = 8) -> list[dict[str, Any]]:
    init_local_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                id, created_at, goal, symbol, asset_kind, action, confidence,
                budget_ok, trade_count, total_pnl, halted, run_json
            FROM micro_strategy_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        try:
            payload = json.loads(str(record.get("run_json") or "{}"))
        except json.JSONDecodeError:
            payload = {}
        record["payload"] = payload if isinstance(payload, dict) else {}
        records.append(record)
    return records


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


def manager_system_prompt() -> str:
    prompts = load_agent_prompts()
    prompt_lines = []
    for agent_id in ["manager", "strategy", "market", "risk", "compliance", "chart", "execution", "report"]:
        item = prompts.get(agent_id) or {}
        prompt_lines.append(f"- {item.get('name', agent_id)}({agent_id}): {item.get('prompt', '')}")
    return (
        MANAGER_SYSTEM_PROMPT
        + "\n\n每个员工的专属 prompt，请调度时尊重：\n"
        + "\n".join(prompt_lines)
    )


def init_state() -> None:
    defaults = {
        "deriv_token": "",
        "llm_provider": "本地规则",
        "llm_api_key": "",
        "llm_model": "local-rule-engine",
        "custom_base_url": "",
        "provider": "本地规则",
        "require_trade_confirmation": True,
        "confirm_next_trade": False,
        "allow_live_execution": False,
        "pending_trade": None,
        "language": "zh",
        "last_language": "zh",
        "messages": [{"role": "assistant", "content": text_for("zh", "initial_message")}],
        "last_candles": None,
        "last_trade_receipt": None,
        "last_tick": None,
        "last_plan": None,
        "prompt_nonce": 0,
        "chart_height": 620,
        "chart_loader_symbol": DEFAULT_SYMBOL,
        "chart_custom_symbol": "",
        "chart_loader_granularity": DEFAULT_GRANULARITY,
        "chart_loader_count": 120,
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
        "advisor_prompt_nonce": 0,
        "advisor_time_budget": 10,
        "advisor_use_web": True,
        "advisor_symbol": DEFAULT_SYMBOL,
        "advisor_runs": [],
        "advisor_evaluations": [],
        "last_advisor_result": None,
        "active_page": "advisor",
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
            --bg: #07100f;
            --panel: #101a17;
            --panel-2: #15231f;
            --panel-3: #0b1513;
            --line: #2a3a36;
            --line-strong: #3f5650;
            --text: #eef6f2;
            --muted: #91a49b;
            --soft: #c8d7d1;
            --green: #00b894;
            --green-2: #7dffcb;
            --cyan: #71d7ff;
            --red: #ff5d5d;
            --amber: #f5b84b;
            --blue: #7aa7ff;
            --accent: #71d7ff;
        }
        .stApp {
            background:
                linear-gradient(135deg, rgba(0,184,148,.06), transparent 32%, rgba(245,184,75,.035) 68%, transparent),
                linear-gradient(90deg, rgba(113,215,255,.04) 1px, transparent 1px),
                linear-gradient(0deg, rgba(0,184,148,.035) 1px, transparent 1px),
                var(--bg);
            background-size: auto, 44px 44px, 44px 44px;
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
            background: linear-gradient(180deg, #06100d, #091714);
            border-right: 1px solid var(--line);
        }
        [data-testid="stSidebar"] > div:first-child {
            padding-top: 1rem;
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
            background:
                linear-gradient(135deg, rgba(17,28,25,.98), rgba(11,21,19,.98) 58%, rgba(19,28,24,.98)),
                repeating-linear-gradient(90deg, rgba(255,255,255,.035) 0, rgba(255,255,255,.035) 1px, transparent 1px, transparent 16px);
            padding: 1rem 1.1rem;
            margin-bottom: 1rem;
            border-radius: 8px;
            box-shadow: 0 16px 42px rgba(0,0,0,.24);
            position: relative;
            overflow: hidden;
        }
        .terminal-hero::after {
            content: "";
            position: absolute;
            inset: 0;
            pointer-events: none;
            background: linear-gradient(120deg, transparent 0%, rgba(255,255,255,.045) 42%, transparent 64%);
            transform: translateX(-46%);
            animation: panelSheen 9s ease-in-out infinite;
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
            letter-spacing: .08em;
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
            border: 1px solid rgba(113,215,255,.42);
            background: rgba(113,215,255,.1);
            color: var(--cyan) !important;
            padding: .4rem .6rem;
            font-size: .78rem;
            font-weight: 900;
            white-space: nowrap;
            border-radius: 7px;
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
            border-radius: 8px;
            box-shadow: 0 14px 36px rgba(0,0,0,.2);
            transition: transform .16s ease, border-color .16s ease, background .16s ease;
        }
        .agent-card:hover {
            transform: translateY(-1px);
            border-color: rgba(125,255,203,.34);
            background: linear-gradient(180deg, rgba(23,43,38,.97), rgba(10,20,17,.98));
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
            border-radius: 8px;
            box-shadow: inset 0 0 18px rgba(0,184,148,.1), 0 0 0 1px rgba(0,184,148,.06);
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
        @keyframes panelSheen {
            0%, 72%, 100% { transform: translateX(-48%); opacity: 0; }
            82% { opacity: .7; }
            92% { transform: translateX(54%); opacity: 0; }
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
            border-radius: 999px;
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
            border-radius: 8px;
        }
        .agent-bubble strong {
            color: var(--green-2) !important;
        }
        [data-testid="stVerticalBlockBorderWrapper"],
        [data-testid="stChatMessage"] {
            border-color: var(--line) !important;
            background: rgba(16,26,23,.92) !important;
            border-radius: 8px !important;
            box-shadow: 0 14px 38px rgba(0,0,0,.2);
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
            border-radius: 8px;
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
            border-radius: 8px;
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
            border-radius: 999px;
        }
        .send-note {
            color: var(--muted) !important;
            font-size: .82rem;
            padding-top: .45rem;
        }
        div[role="radiogroup"] {
            gap: .45rem;
        }
        div[role="radiogroup"] label {
            border: 1px solid rgba(145,164,155,.26);
            background: rgba(12,24,20,.74);
            padding: .35rem .75rem;
            min-height: 2.25rem;
            border-radius: 8px;
        }
        div[role="radiogroup"] label:hover {
            border-color: rgba(125,255,203,.52);
            background: rgba(28,55,48,.82);
        }
        .page-context {
            border: 1px solid rgba(113,215,255,.22);
            border-left: 3px solid var(--accent);
            background: linear-gradient(90deg, rgba(113,215,255,.09), rgba(15,28,24,.62));
            padding: .72rem .9rem;
            margin: .6rem 0 1rem;
            border-radius: 8px;
        }
        .page-context strong {
            color: var(--text);
            font-weight: 950;
            margin-right: .7rem;
        }
        .page-context span {
            color: var(--muted);
            font-size: .88rem;
        }
        .workspace-head {
            display: flex;
            align-items: end;
            justify-content: space-between;
            gap: 1rem;
            margin: .25rem 0 .55rem;
        }
        .workspace-title {
            color: var(--text) !important;
            font-size: 1rem;
            font-weight: 950;
            text-transform: uppercase;
            letter-spacing: .06em;
        }
        .workspace-route {
            color: var(--muted) !important;
            font-size: .78rem;
            font-weight: 800;
        }
        .nav-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: .55rem;
            margin-bottom: .55rem;
        }
        .nav-card {
            border: 1px solid rgba(145,164,155,.2);
            background: linear-gradient(180deg, rgba(16,30,26,.82), rgba(8,17,15,.88));
            border-radius: 8px;
            padding: .68rem .72rem;
            min-height: 94px;
            box-shadow: 0 10px 26px rgba(0,0,0,.16);
        }
        .nav-card.active {
            border-color: rgba(113,215,255,.54);
            background: linear-gradient(180deg, rgba(22,42,38,.95), rgba(9,20,18,.95));
            box-shadow: inset 0 1px 0 rgba(255,255,255,.06), 0 14px 34px rgba(0,0,0,.2);
        }
        .nav-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: .5rem;
            margin-bottom: .42rem;
        }
        .nav-code {
            width: 30px;
            height: 30px;
            display: grid;
            place-items: center;
            border: 1px solid rgba(113,215,255,.34);
            background: rgba(113,215,255,.1);
            color: var(--cyan) !important;
            border-radius: 8px;
            font-weight: 950;
            font-size: .78rem;
        }
        .nav-state {
            color: var(--muted) !important;
            font-size: .68rem;
            font-weight: 900;
            text-transform: uppercase;
        }
        .nav-card.active .nav-state {
            color: var(--green-2) !important;
        }
        .nav-label {
            color: var(--text) !important;
            font-size: .94rem;
            font-weight: 950;
            line-height: 1.15;
        }
        .nav-caption {
            color: var(--muted) !important;
            font-size: .74rem;
            line-height: 1.35;
            margin-top: .25rem;
        }
        .global-status {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: .55rem;
            margin: -.2rem 0 1rem;
        }
        .status-cell {
            border: 1px solid rgba(145,164,155,.22);
            background: linear-gradient(180deg, rgba(18,31,28,.86), rgba(7,16,14,.9));
            border-radius: 8px;
            padding: .58rem .7rem;
            min-height: 58px;
            box-shadow: 0 10px 24px rgba(0,0,0,.14);
        }
        .status-cell span {
            display: block;
            color: var(--muted) !important;
            font-size: .72rem;
            font-weight: 850;
            text-transform: uppercase;
            margin-bottom: .15rem;
        }
        .status-cell strong {
            color: var(--text) !important;
            font-size: .98rem;
            font-weight: 950;
            line-height: 1.18;
        }
        .status-cell.attention {
            border-color: rgba(245,184,75,.5);
            background: linear-gradient(180deg, rgba(72,53,20,.72), rgba(22,18,10,.84));
        }
        .safety-panel {
            border: 1px solid rgba(145,164,155,.24);
            background: linear-gradient(180deg, rgba(13,27,23,.88), rgba(7,15,13,.9));
            border-radius: 8px;
            padding: .85rem;
            margin: 0 0 1rem;
            box-shadow: 0 14px 34px rgba(0,0,0,.18);
        }
        .safety-title {
            color: var(--text) !important;
            font-weight: 950;
            margin-bottom: .65rem;
        }
        .safety-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
            gap: .55rem;
        }
        .safety-cell {
            border: 1px solid rgba(145,164,155,.22);
            background: rgba(255,255,255,.045);
            border-radius: 8px;
            padding: .55rem .65rem;
        }
        .safety-cell.ok {
            border-color: rgba(0,184,148,.34);
        }
        .safety-cell.warn {
            border-color: rgba(245,184,75,.45);
            background: rgba(245,184,75,.08);
        }
        .safety-cell span {
            display: block;
            color: var(--muted) !important;
            font-size: .72rem;
            font-weight: 850;
            text-transform: uppercase;
        }
        .safety-cell strong {
            color: var(--text) !important;
            font-size: .95rem;
            font-weight: 950;
        }
        .pending-panel {
            border: 1px solid rgba(245,184,75,.34);
            background: linear-gradient(180deg, rgba(54,41,19,.62), rgba(15,14,10,.88));
            border-radius: 8px;
            padding: .85rem;
            margin: 0 0 1rem;
        }
        .pending-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: .5rem;
        }
        .pending-grid > div {
            border: 1px solid rgba(255,255,255,.12);
            background: rgba(255,255,255,.045);
            border-radius: 8px;
            padding: .52rem .62rem;
            min-width: 0;
        }
        .pending-grid > div.ok {
            border-color: rgba(0,184,148,.34);
        }
        .pending-grid > div.warn {
            border-color: rgba(245,184,75,.5);
            background: rgba(245,184,75,.09);
        }
        .pending-grid span {
            display: block;
            color: var(--muted) !important;
            font-size: .7rem;
            font-weight: 850;
            text-transform: uppercase;
            margin-bottom: .15rem;
        }
        .pending-grid strong {
            display: block;
            color: var(--text) !important;
            font-size: .9rem;
            font-weight: 900;
            line-height: 1.18;
            overflow-wrap: anywhere;
        }
        .advisor-room {
            border: 1px solid var(--line);
            background: linear-gradient(135deg, rgba(17,30,27,.98), rgba(9,18,16,.98));
            padding: 1rem;
            margin: 0 0 1rem;
            border-radius: 8px;
            box-shadow: 0 16px 44px rgba(0,0,0,.22);
        }
        .advisor-room-head {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            align-items: flex-start;
            margin-bottom: .75rem;
        }
        .advisor-title {
            color: var(--text) !important;
            font-size: 1.18rem;
            font-weight: 950;
        }
        .advisor-caption {
            color: var(--muted) !important;
            font-size: .86rem;
            line-height: 1.48;
            max-width: 900px;
        }
        .advisor-deadline {
            border: 1px solid rgba(245,184,75,.45);
            background: rgba(245,184,75,.12);
            color: #ffd886 !important;
            padding: .35rem .55rem;
            font-size: .76rem;
            font-weight: 900;
            white-space: nowrap;
            border-radius: 7px;
        }
        .advisor-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            gap: .65rem;
            margin-top: .7rem;
        }
        .advisor-card {
            border: 1px solid rgba(145,164,155,.28);
            background: rgba(255,255,255,.045);
            padding: .75rem;
            min-height: 150px;
            border-radius: 8px;
        }
        .advisor-card-top {
            display: flex;
            align-items: center;
            gap: .55rem;
            margin-bottom: .45rem;
        }
        .advisor-code {
            width: 34px;
            height: 34px;
            display: grid;
            place-items: center;
            border: 1px solid rgba(122,167,255,.42);
            background: rgba(122,167,255,.12);
            color: var(--text) !important;
            font-weight: 950;
            border-radius: 8px;
        }
        .advisor-name {
            font-weight: 900;
            color: var(--text) !important;
            line-height: 1.25;
        }
        .advisor-role {
            color: var(--muted) !important;
            font-size: .76rem;
            line-height: 1.3;
        }
        .advisor-stance {
            display: inline-block;
            margin: .15rem 0 .4rem;
            padding: .18rem .42rem;
            border: 1px solid rgba(0,184,148,.38);
            color: var(--green-2) !important;
            background: rgba(0,184,148,.11);
            font-size: .76rem;
            font-weight: 950;
            border-radius: 999px;
        }
        .advisor-copy {
            color: var(--soft) !important;
            font-size: .82rem;
            line-height: 1.45;
        }
        .advisor-result {
            border: 1px solid rgba(0,184,148,.42);
            background: rgba(0,184,148,.1);
            padding: .85rem;
            margin-top: .75rem;
            border-radius: 8px;
        }
        .advisor-result strong {
            color: var(--green-2) !important;
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
            border-radius: 8px;
            border: 1px solid var(--line);
            background: #13231f;
            color: var(--text);
            font-weight: 900;
            transition: transform .14s ease, border-color .14s ease, background .14s ease;
        }
        .stButton > button:hover {
            transform: translateY(-1px);
            border-color: rgba(125,255,203,.42);
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
            border-radius: 8px;
            box-shadow: 0 16px 44px rgba(0,0,0,.22);
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
            border-radius: 8px;
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
            border-radius: 8px;
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
            .workspace-head {
                display: block;
            }
            .nav-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .terminal-title {
                font-size: 1.55rem;
            }
            .block-container {
                padding-left: .85rem;
                padding-right: .85rem;
            }
            .global-status {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .safety-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        @media (max-width: 560px) {
            .nav-grid {
                grid-template-columns: 1fr;
            }
        }
        @media (prefers-reduced-motion: reduce) {
            .terminal-hero::after {
                animation: none;
            }
            .agent-card,
            .stButton > button {
                transition: none;
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

        st.subheader(t("execution_safety"))
        st.session_state.require_trade_confirmation = st.toggle(
            t("require_trade_confirmation"),
            value=bool(st.session_state.require_trade_confirmation),
            help="建议保持开启。每次下单后会自动取消确认。",
        )
        st.session_state.confirm_next_trade = st.checkbox(
            t("confirm_next_trade"),
            value=bool(st.session_state.confirm_next_trade),
        )
        st.session_state.allow_live_execution = st.checkbox(
            t("allow_live_execution"),
            value=bool(st.session_state.allow_live_execution),
            help="默认关闭。开启后服务端仍会要求显式 allow_live=true。",
        )
        render_pending_trade_panel(show_raw=True)

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
        st.caption(f"Agent prompts: `{AGENT_PROMPTS_PATH}`")

        st.divider()
        st.subheader(t("history"))
        for row in load_recent_runs(5):
            status = "OK" if row["ok"] else "BLOCKED"
            with st.expander(f"#{row['id']} · {status} · {row['created_at'][:16]}", expanded=False):
                st.caption(row["user_prompt"])
                st.write(row["final_answer"])
        for row in load_recent_advisor_runs(3):
            with st.expander(
                f"谋士 #{row['id']} · {row['symbol']} · {float(row['confidence']):.0%}",
                expanded=False,
            ):
                st.caption(row["question"])
                st.write(row["consensus"])

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
            st.session_state.advisor_runs = []
            st.session_state.last_advisor_result = None
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
        "买",
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


def normalize_deriv_symbol(symbol: str) -> str:
    raw = symbol.strip()
    if not raw:
        return DEFAULT_SYMBOL
    upper = raw.upper()
    compact_volatility = re.fullmatch(r"R(\d+)", upper)
    if compact_volatility:
        return f"R_{compact_volatility.group(1)}"
    if upper == "STPRNG":
        return "stpRNG"
    if upper.startswith("FRX") and len(upper) == 9:
        return "frx" + upper[3:]
    return upper


def selected_chart_symbol(selection: str, custom_symbol: str) -> str:
    raw = (custom_symbol or "").strip() or (selection or "").strip() or DEFAULT_SYMBOL
    return normalize_deriv_symbol(raw)


def chart_granularity_label(seconds: int) -> str:
    seconds = int(seconds)
    if seconds >= 3600 and seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours}小时" if current_lang() == "zh" else f"{hours}h"
    minutes = max(1, seconds // 60)
    return f"{minutes}分钟" if current_lang() == "zh" else f"{minutes}m"


def extract_symbol(text: str) -> str:
    symbol_match = re.search(
        r"\b(?:R_?\d+|1HZ\d+V|BOOM\d+|CRASH\d+|JD\d+|RDBULL|RDBEAR|stpRNG|frx[A-Za-z]{6})\b",
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


def advisor_name(advisor: dict[str, str], lang: str | None = None) -> str:
    return advisor["zh_name"] if (lang or current_lang()) == "zh" else advisor["en_name"]


def advisor_role(advisor: dict[str, str], lang: str | None = None) -> str:
    return advisor["zh_role"] if (lang or current_lang()) == "zh" else advisor["en_role"]


def clean_feed_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def parse_rss_items(xml_text: str, limit: int) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        title = clean_feed_text(item.findtext("title"))
        link = clean_feed_text(item.findtext("link"))
        source = clean_feed_text(item.findtext("source")) or urllib.parse.urlparse(link).netloc
        published = clean_feed_text(item.findtext("pubDate"))
        if title and link:
            items.append(
                {
                    "title": title,
                    "url": link,
                    "source": source or "web",
                    "published": published,
                }
            )
        if len(items) >= limit:
            break
    return items


def fetch_news_rss(query: str, limit: int, timeout_seconds: float) -> list[dict[str, str]]:
    try:
        import httpx

        encoded = urllib.parse.quote_plus(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
        with httpx.Client(
            timeout=max(1.0, timeout_seconds),
            headers={"User-Agent": "DerivSmartTradingGateway/1.0"},
            follow_redirects=True,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            return parse_rss_items(response.text, limit)
    except Exception:
        return []


def build_advisor_queries(question: str, symbol: str) -> list[str]:
    symbol_query = symbol
    if symbol.upper().startswith("R_"):
        symbol_query = f'Deriv "{symbol}" volatility index'
    if symbol.lower().startswith("frx"):
        symbol_query = f"{symbol[3:6]} {symbol[6:]} forex"
    base = re.sub(r"\s+", " ", question).strip()
    return [
        f"{symbol_query} latest market news",
        f"{symbol_query} short term volatility trading",
        f"{base} market news",
    ]


def collect_advisor_web_context(
    question: str,
    symbol: str,
    time_budget_seconds: int,
    use_web: bool,
    writer: Callable[[str], None] | None = None,
) -> list[dict[str, str]]:
    if not use_web:
        return []
    started = time.perf_counter()
    queries = build_advisor_queries(question, symbol)
    web_deadline = max(1.0, min(float(time_budget_seconds) * 0.35, 3.0))
    per_query_timeout = max(0.8, min(1.4, web_deadline / max(len(queries), 1) + 0.4))
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(3, len(queries))) as pool:
        futures = {
            pool.submit(fetch_news_rss, query, 4, per_query_timeout): query
            for query in queries
        }
        try:
            for future in concurrent.futures.as_completed(
                futures,
                timeout=web_deadline,
            ):
                for item in future.result():
                    key = item.get("url") or item.get("title")
                    if key and key not in seen:
                        item["query"] = futures[future]
                        sources.append(item)
                        seen.add(key)
                if len(sources) >= 8 or (time.perf_counter() - started) > web_deadline:
                    break
        except concurrent.futures.TimeoutError:
            pass
    if writer:
        writer(f"Web research -> {len(sources)} sources within {time.perf_counter() - started:.1f}s")
    return sources[:8]


def headline_sentiment(sources: list[dict[str, str]]) -> dict[str, Any]:
    positive_words = ["rise", "rally", "bull", "gain", "up", "strong", "surge", "突破", "上涨", "走强", "利好"]
    negative_words = ["fall", "drop", "bear", "down", "weak", "risk", "sell", "跌", "下跌", "走弱", "风险"]
    positive = 0
    negative = 0
    for source in sources:
        title = source.get("title", "").lower()
        positive += sum(1 for word in positive_words if word in title)
        negative += sum(1 for word in negative_words if word in title)
    if positive > negative:
        label = "bullish"
    elif negative > positive:
        label = "bearish"
    else:
        label = "mixed"
    return {"label": label, "positive": positive, "negative": negative}


def advisor_market_snapshot(
    symbol: str,
    started_at: float,
    time_budget_seconds: int,
    writer: Callable[[str], None] | None = None,
    *,
    persist_state: bool = True,
    trace_api: bool = True,
) -> dict[str, Any]:
    market: dict[str, Any] = {"symbol": symbol, "tick": None, "candles": None, "summary": "no market data"}
    deadline_at = started_at + max(4, time_budget_seconds)
    tick_result = call_deriv_tool_before_deadline(
        "get_market_ticks",
        lambda: get_market_ticks(symbol, False),
        {"symbol": symbol, "subscribe": False, "advisor": True},
        deadline_at,
        writer,
        trace_api=trace_api,
    )
    if tick_result.get("ok"):
        market["tick_result"] = tick_result
        market["tick"] = ((tick_result.get("data") or {}).get("tick") or {})
        if persist_state and in_streamlit_runtime():
            st.session_state.last_tick = tick_result

    remaining = deadline_at - time.perf_counter()
    if remaining > 2.8:
        candle_result = call_deriv_tool_before_deadline(
            "get_historical_candles",
            lambda: get_historical_candles(symbol, 60, 60),
            {"symbol": symbol, "granularity": 60, "count": 60, "advisor": True},
            deadline_at,
            writer,
            trace_api=trace_api,
        )
        if candle_result.get("ok"):
            market["candles"] = candle_result
            if persist_state and in_streamlit_runtime():
                st.session_state.last_candles = candle_result

    frame = candles_frame_from_result(market.get("candles"))
    latest_quote = (market.get("tick") or {}).get("quote")
    if not frame.empty:
        first_close = float(frame.iloc[0]["close"])
        latest_close = float(frame.iloc[-1]["close"])
        ma5 = float(frame.iloc[-1]["ma5"]) if not math.isnan(float(frame.iloc[-1]["ma5"])) else latest_close
        ma20 = float(frame.iloc[-1]["ma20"]) if not math.isnan(float(frame.iloc[-1]["ma20"])) else latest_close
        change_pct = (latest_close - first_close) / first_close * 100 if first_close else 0.0
        if latest_close > first_close and ma5 >= ma20:
            trend = "up"
        elif latest_close < first_close and ma5 <= ma20:
            trend = "down"
        else:
            trend = "mixed"
        market.update(
            {
                "trend": trend,
                "latest_close": latest_close,
                "change_pct": change_pct,
                "ma5": ma5,
                "ma20": ma20,
                "summary": f"{symbol} 60m window trend={trend}, change={change_pct:+.2f}%, ma5={ma5:.5g}, ma20={ma20:.5g}",
            }
        )
    elif latest_quote is not None:
        market.update({"trend": "tick_only", "summary": f"{symbol} latest tick={latest_quote}"})
    return market


def persist_advisor_market_state(market: dict[str, Any]) -> None:
    if not in_streamlit_runtime():
        return
    tick_result = market.get("tick_result")
    if isinstance(tick_result, dict) and tick_result.get("ok"):
        st.session_state.last_tick = tick_result
    candle_result = market.get("candles")
    if isinstance(candle_result, dict) and candle_result.get("ok"):
        st.session_state.last_candles = candle_result


def stance_from_market_and_news(market: dict[str, Any], news_signal: dict[str, Any]) -> str:
    trend = market.get("trend")
    if trend == "up" and news_signal.get("label") != "bearish":
        return "CALL"
    if trend == "down" and news_signal.get("label") != "bullish":
        return "PUT"
    return "WAIT"


def local_advisor_opinion(
    advisor: dict[str, str],
    question: str,
    market: dict[str, Any],
    sources: list[dict[str, str]],
    news_signal: dict[str, Any],
    lang: str | None = None,
) -> dict[str, Any]:
    advisor_id = advisor["id"]
    prompt = agent_prompt(f"advisor.{advisor_id}")
    base_stance = stance_from_market_and_news(market, news_signal)
    source_count = len(sources)
    trend = market.get("trend", "unknown")
    latest = market.get("latest_close") or (market.get("tick") or {}).get("quote")
    if advisor_id == "risk":
        stance = "WAIT" if base_stance != "WAIT" and source_count == 0 else base_stance
        rationale = "没有网页确认时降低仓位和冲动；若要做，只做 demo 小额并保留撤退条件。"
        invalidation = "最新 Tick 反向突破或连续三根反向波动。"
    elif advisor_id == "contrarian":
        stance = "WAIT" if base_stance in {"CALL", "PUT"} else "CALL" if trend == "down" else "PUT"
        rationale = "反方视角：短线共识可能已经被价格吸收，必须等下一根确认。"
        invalidation = "若价格继续沿原方向扩大并伴随新闻确认，反方观点失效。"
    elif advisor_id == "quant":
        stance = base_stance
        rationale = f"量化视角看 {market.get('summary')}；趋势不干净就不追。"
        invalidation = "MA5/MA20 关系反转，或最新价跌回本轮窗口中位。"
    elif advisor_id == "macro":
        stance = base_stance if news_signal.get("label") != "mixed" else "WAIT"
        rationale = f"网页情绪={news_signal.get('label')}，来源={source_count} 条；没有外部催化就不加速。"
        invalidation = "出现新的高影响消息或相关新闻标题方向反转。"
    else:
        stance = base_stance
        rationale = f"盘口节奏倾向 {base_stance}，最新价/收盘={latest}；等待短周期确认后再交给执行链。"
        invalidation = "报价停滞、跳动变慢或连续反向 Tick。"
    return {
        "advisor_id": advisor_id,
        "name": advisor_name(advisor, lang),
        "role": advisor_role(advisor, lang),
        "prompt": prompt,
        "stance": stance,
        "rationale": rationale,
        "invalidation": invalidation,
        "question": question,
    }


def consensus_from_opinions(opinions: list[dict[str, Any]], market: dict[str, Any], sources: list[dict[str, str]]) -> dict[str, Any]:
    votes = [str(item.get("stance") or "WAIT") for item in opinions]
    counts = {stance: votes.count(stance) for stance in {"CALL", "PUT", "WAIT"}}
    winner = max(counts, key=counts.get)
    support = counts[winner] / max(len(votes), 1)
    data_bonus = 0.12 if market.get("candles") else 0.04
    web_bonus = min(len(sources), 6) * 0.025
    confidence = min(0.92, max(0.25, support * 0.62 + data_bonus + web_bonus))
    if winner == "CALL":
        summary = "谋士团偏向看涨/做多，但只建议进入原交易链复核，不直接下单。"
    elif winner == "PUT":
        summary = "谋士团偏向看跌/做空，但只建议进入原交易链复核，不直接下单。"
    else:
        summary = "谋士团建议等待，当前信息不足以支持短线立即出手。"
    return {
        "stance": winner,
        "summary": summary,
        "confidence": round(confidence, 3),
        "vote_counts": counts,
    }


def advisor_llm_synthesis(
    question: str,
    symbol: str,
    market: dict[str, Any],
    sources: list[dict[str, str]],
    opinions: list[dict[str, Any]],
    consensus: dict[str, Any],
    remaining_seconds: float,
) -> str | None:
    if not in_streamlit_runtime():
        return None
    provider: Provider = st.session_state.llm_provider
    if provider == "本地规则" or not st.session_state.llm_api_key or remaining_seconds < 2.5:
        return None
    source_lines = "\n".join(
        f"- {item.get('title')} ({item.get('source')}, {item.get('published')})"
        for item in sources[:6]
    ) or "- no web source"
    opinion_lines = "\n".join(
        f"- {item['name']}: {item['stance']} | {item['rationale']} | invalidation: {item['invalidation']}"
        for item in opinions
    )
    prompt = f"""
你是首席谋士。你的专属 prompt：
{agent_prompt("advisor.chief")}

请基于下列材料，在 120 字以内给老板一个短线交易决策建议。
要求：必须包含 方向(CALL/PUT/WAIT)、置信度、执行前提、失效条件。不要建议绕过人工确认。

问题: {question}
Symbol: {symbol}
行情: {json.dumps(market, ensure_ascii=False, default=str)[:2500]}
网页来源:
{source_lines}
谋士观点:
{opinion_lines}
本地一致结论: {json.dumps(consensus, ensure_ascii=False)}
""".strip()
    try:
        if provider in {"OpenAI", "DeepSeek", "OpenAI-Compatible"}:
            from openai import OpenAI

            base_url = OPENAI_COMPATIBLE_BASE_URLS.get(provider)
            if provider == "OpenAI-Compatible":
                base_url = st.session_state.custom_base_url.strip() or None
                if not base_url:
                    return None
            kwargs: dict[str, Any] = {
                "api_key": st.session_state.llm_api_key,
                "timeout": max(2.0, min(8.0, remaining_seconds)),
            }
            if base_url:
                kwargs["base_url"] = base_url
            client = OpenAI(**kwargs)
            response = client.chat.completions.create(
                model=st.session_state.llm_model,
                messages=[
                    {"role": "system", "content": "你输出简洁、可审计、适合短线交易前复核的中文建议。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.15,
                max_tokens=220,
            )
            return (response.choices[0].message.content or "").strip() or None
        if provider == "Anthropic":
            from anthropic import Anthropic

            client = Anthropic(api_key=st.session_state.llm_api_key, timeout=max(2.0, min(8.0, remaining_seconds)))
            response = client.messages.create(
                model=st.session_state.llm_model,
                max_tokens=220,
                temperature=0.15,
                system="你输出简洁、可审计、适合短线交易前复核的中文建议。",
                messages=[{"role": "user", "content": prompt}],
            )
            return "\n".join(
                block.text for block in response.content if getattr(block, "type", None) == "text"
            ).strip() or None
    except Exception:
        return None
    return None


def llm_provider_ready() -> bool:
    if not in_streamlit_runtime():
        return False
    provider: Provider = st.session_state.llm_provider
    if provider == "本地规则" or not st.session_state.llm_api_key:
        return False
    if provider == "OpenAI-Compatible" and not st.session_state.custom_base_url.strip():
        return False
    return True


def agent_ai_brief(
    agent_id: str,
    *,
    task: str,
    context: dict[str, Any],
    max_tokens: int = 220,
) -> str | None:
    if not llm_provider_ready():
        return None
    provider: Provider = st.session_state.llm_provider
    prompt = f"""
你是一个多 Agent 交易系统里的独立子 Agent。
你的身份 prompt：
{agent_prompt(agent_id)}

请只基于给定上下文输出你的专业结论。
要求：
- 用中文，80-160 字。
- 说清楚你看到的数据、你的判断、下一步。
- 如果是执行/风控/合规相关，不允许建议绕过人工确认、Token 检查、demo/live 安全边界。
- 不要输出 Markdown 表格，不要输出隐藏推理。

任务: {task}
上下文 JSON:
{json.dumps(context, ensure_ascii=False, default=str)[:4000]}
""".strip()
    try:
        if provider in {"OpenAI", "DeepSeek", "OpenAI-Compatible"}:
            from openai import OpenAI

            base_url = OPENAI_COMPATIBLE_BASE_URLS.get(provider)
            if provider == "OpenAI-Compatible":
                base_url = st.session_state.custom_base_url.strip() or None
            kwargs: dict[str, Any] = {"api_key": st.session_state.llm_api_key, "timeout": 8.0}
            if base_url:
                kwargs["base_url"] = base_url
            client = OpenAI(**kwargs)
            response = client.chat.completions.create(
                model=st.session_state.llm_model,
                messages=[
                    {"role": "system", "content": "你是交易系统里的专业子 Agent，只输出可审计的中文行动结论。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.15,
                max_tokens=max_tokens,
            )
            return (response.choices[0].message.content or "").strip() or None
        if provider == "Anthropic":
            from anthropic import Anthropic

            client = Anthropic(api_key=st.session_state.llm_api_key, timeout=8.0)
            response = client.messages.create(
                model=st.session_state.llm_model,
                max_tokens=max_tokens,
                temperature=0.15,
                system="你是交易系统里的专业子 Agent，只输出可审计的中文行动结论。",
                messages=[{"role": "user", "content": prompt}],
            )
            return "\n".join(
                block.text for block in response.content if getattr(block, "type", None) == "text"
            ).strip() or None
    except Exception as exc:
        return f"AI 子 Agent 调用失败，已使用本地安全逻辑兜底：{exc}"
    return None


def attach_agent_ai_brief(
    report: dict[str, Any],
    agent_id: str,
    *,
    task: str,
    context: dict[str, Any],
    events: list[AgentEvent],
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    brief = agent_ai_brief(agent_id, task=task, context=context)
    report["ai_enabled"] = llm_provider_ready()
    if brief:
        report["ai_brief"] = brief
        append_team_event(events, agent_name(agent_id), "经理", f"AI判断：{brief}", writer)
    return report


def advisor_langgraph_available() -> bool:
    try:
        import langgraph  # noqa: F401

        return True
    except Exception:
        return False


def make_langgraph_advisor_node(advisor: dict[str, str]) -> Callable[[AdvisorGraphState], dict[str, Any]]:
    def node(state: AdvisorGraphState) -> dict[str, Any]:
        opinion = local_advisor_opinion(
            advisor,
            str(state.get("question") or ""),
            dict(state.get("market") or {}),
            list(state.get("sources") or []),
            dict(state.get("news_signal") or {}),
            str(state.get("language") or "zh"),
        )
        return {
            "opinions": [opinion],
            "logs": [f"{opinion['name']} -> {opinion['stance']}: {opinion['rationale']}"],
        }

    return node


def build_advisor_langgraph() -> Any:
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(AdvisorGraphState)

    def web_research_node(state: AdvisorGraphState) -> dict[str, Any]:
        started = time.perf_counter()
        sources = collect_advisor_web_context(
            str(state.get("question") or ""),
            str(state.get("symbol") or DEFAULT_SYMBOL),
            int(state.get("budget") or 10),
            bool(state.get("use_web")),
            None,
        )
        return {
            "sources": sources,
            "graph_runtime": "langgraph",
            "logs": [f"Web research -> {len(sources)} sources within {time.perf_counter() - started:.1f}s"],
        }

    def market_snapshot_node(state: AdvisorGraphState) -> dict[str, Any]:
        market = advisor_market_snapshot(
            str(state.get("symbol") or DEFAULT_SYMBOL),
            float(state.get("started_at") or time.perf_counter()),
            int(state.get("budget") or 10),
            None,
            persist_state=False,
            trace_api=False,
        )
        return {"market": market, "logs": [f"Market snapshot -> {market.get('summary', 'no market data')}"]}

    def news_signal_node(state: AdvisorGraphState) -> dict[str, Any]:
        return {"news_signal": headline_sentiment(list(state.get("sources") or []))}

    def synthesize_node(state: AdvisorGraphState) -> dict[str, Any]:
        opinions = list(state.get("opinions") or [])
        sources = list(state.get("sources") or [])
        market = dict(state.get("market") or {})
        local_consensus = consensus_from_opinions(opinions, market, sources)
        remaining = int(state.get("budget") or 10) - (
            time.perf_counter() - float(state.get("started_at") or time.perf_counter())
        )
        llm_summary = advisor_llm_synthesis(
            str(state.get("question") or ""),
            str(state.get("symbol") or DEFAULT_SYMBOL),
            market,
            sources,
            opinions,
            local_consensus,
            remaining,
        )
        final_summary = llm_summary or (
            f"{local_consensus['summary']} 方向={local_consensus['stance']}，"
            f"置信度={local_consensus['confidence']:.0%}；执行前先让行情、风控、合规和执行交易员复核。"
        )
        return {
            "local_consensus": local_consensus,
            "consensus": final_summary,
            "stance": local_consensus["stance"],
            "confidence": local_consensus["confidence"],
            "vote_counts": local_consensus["vote_counts"],
            "logs": [f"Chief Advisor -> {local_consensus['stance']} confidence={local_consensus['confidence']:.0%}"],
        }

    graph.add_node("web_research", web_research_node)
    graph.add_node("market_snapshot", market_snapshot_node)
    graph.add_node("news_signal", news_signal_node)
    for advisor in advisor_specs():
        graph.add_node(advisor_node_name(advisor["id"]), make_langgraph_advisor_node(advisor))
    graph.add_node("synthesize", synthesize_node)

    graph.add_edge(START, "web_research")
    graph.add_edge("web_research", "market_snapshot")
    graph.add_edge("market_snapshot", "news_signal")
    for advisor in advisor_specs():
        node_name = advisor_node_name(advisor["id"])
        graph.add_edge("news_signal", node_name)
        graph.add_edge(node_name, "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


def run_advisor_langgraph(
    question: str,
    symbol: str,
    budget: int,
    use_web: bool,
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any] | None:
    try:
        app = build_advisor_langgraph()
        return dict(
            app.invoke(
                {
                    "question": question,
                    "symbol": symbol,
                    "budget": budget,
                    "use_web": use_web,
                    "language": current_lang(),
                    "started_at": time.perf_counter(),
                    "opinions": [],
                    "logs": [],
                }
            )
        )
    except Exception as exc:
        if writer:
            writer(f"LangGraph unavailable, fallback to local council: {exc}")
        push_runtime_event("langgraph", "Advisor Graph", "Fallback", str(exc))
        return None


def run_advisor_council(
    question: str,
    symbol: str,
    time_budget_seconds: int,
    use_web: bool,
    writer: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    budget = max(4, min(int(time_budget_seconds), 25))
    push_runtime_event("advisor", "Boss", "Advisor Council", f"question received: {question[:80]}")
    if writer:
        writer(f"Advisor Council START · budget={budget}s · symbol={symbol}")

    graph_state = run_advisor_langgraph(question, symbol, budget, use_web, writer)
    if graph_state:
        sources = list(graph_state.get("sources") or [])
        market = dict(graph_state.get("market") or {})
        news_signal = dict(graph_state.get("news_signal") or {})
        opinions = list(graph_state.get("opinions") or [])
        final_summary = str(graph_state.get("consensus") or "")
        stance = str(graph_state.get("stance") or "WAIT")
        confidence = float(graph_state.get("confidence") or 0)
        vote_counts = dict(graph_state.get("vote_counts") or {})
        runtime = "langgraph"
        persist_advisor_market_state(market)
        for line in graph_state.get("logs") or []:
            if writer:
                writer(str(line))
            push_runtime_event("langgraph", "Advisor Graph", "Log", str(line))
    else:
        sources = collect_advisor_web_context(question, symbol, budget, use_web, writer)
        market = advisor_market_snapshot(symbol, started, budget, writer)
        news_signal = headline_sentiment(sources)
        opinions = [
            local_advisor_opinion(advisor, question, market, sources, news_signal)
            for advisor in advisor_specs()
        ]
        for opinion in opinions:
            push_runtime_event("advisor", opinion["name"], "Chief Advisor", f"{opinion['stance']}: {opinion['rationale']}")
            if writer:
                writer(f"{opinion['name']} -> {opinion['stance']}: {opinion['rationale']}")

        consensus = consensus_from_opinions(opinions, market, sources)
        remaining = budget - (time.perf_counter() - started)
        llm_summary = advisor_llm_synthesis(
            question,
            symbol,
            market,
            sources,
            opinions,
            consensus,
            remaining,
        )
        final_summary = llm_summary or (
            f"{consensus['summary']} 方向={consensus['stance']}，"
            f"置信度={consensus['confidence']:.0%}；执行前先让行情、风控、合规和执行交易员复核。"
        )
        stance = consensus["stance"]
        confidence = consensus["confidence"]
        vote_counts = consensus["vote_counts"]
        runtime = "local_fallback"

    elapsed_ms = (time.perf_counter() - started) * 1000
    entry_price = advisor_entry_price(market)
    result = {
        "ok": True,
        "question": question,
        "symbol": symbol,
        "runtime": runtime,
        "time_budget_seconds": budget,
        "elapsed_ms": round(elapsed_ms, 1),
        "used_web": bool(use_web),
        "source_count": len(sources),
        "sources": sources,
        "market": market,
        "news_signal": news_signal,
        "opinions": opinions,
        "consensus": final_summary,
        "stance": stance,
        "confidence": confidence,
        "vote_counts": vote_counts,
        "entry_price": entry_price,
        "evaluation": evaluate_advisor_outcome(stance, entry_price, None, confidence),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if in_streamlit_runtime():
        st.session_state.last_advisor_result = result
        st.session_state.advisor_runs = [result] + st.session_state.get("advisor_runs", [])[:5]
    save_advisor_run(result)
    push_runtime_event(
        "advisor",
        "Chief Advisor",
        "Boss",
        f"{stance} confidence={confidence:.0%}",
        {"elapsed_ms": elapsed_ms, "sources": len(sources)},
    )
    return result


def run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


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
    if not in_streamlit_runtime():
        return
    event = {
        "time": datetime.now(LOCAL_TZ).strftime("%H:%M:%S.%f")[:-3],
        "kind": kind,
        "source": source,
        "target": target,
        "message": message,
        "payload": payload or {},
    }
    append_runtime_event_to_state(st.session_state, event)


def append_runtime_event_to_state(state: Any, event: dict[str, Any], limit: int = 120) -> None:
    current_events = list(state.get("runtime_events", []))
    state["runtime_events"] = (current_events + [event])[-limit:]
    state["sync_version"] = int(state.get("sync_version", 0)) + 1


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
    if not in_streamlit_runtime():
        return
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
        return f"{data.get('account_type', 'demo')} contract_id={receipt.get('contract_id')}"
    if data.get("sell"):
        sell = data["sell"]
        return f"closed contract_id={data.get('contract_id') or sell.get('contract_id')} sold_for={sell.get('sold_for')}"
    if data.get("contract"):
        contract = data["contract"]
        status = contract.get("status") or ("open" if contract else "none")
        return f"contract status={status} id={contract.get('contract_id')}"
    if data.get("balance") or data.get("portfolio"):
        return f"{data.get('account_type', 'account')} status loaded"
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


def call_deriv_tool_before_deadline(
    tool_name: str,
    coro_factory: Callable[[], Any],
    params: dict[str, Any],
    deadline_at: float,
    writer: Callable[[str], None] | None = None,
    *,
    trace_api: bool = True,
) -> dict[str, Any]:
    remaining = deadline_at - time.perf_counter()
    if remaining < 0.8:
        result = {"ok": False, "error": {"message": "advisor deadline reached before API call"}}
        if trace_api:
            record_api_trace(tool_name, "SKIPPED", params, result, 0)
        if writer:
            writer(f"API {tool_name} -> SKIPPED deadline reached")
        return result

    if trace_api:
        record_api_trace(tool_name, "START", params)
    started = time.perf_counter()
    try:
        result = parse_tool_response(run_async(asyncio.wait_for(coro_factory(), timeout=remaining)))
    except TimeoutError:
        result = {"ok": False, "error": {"message": "advisor deadline reached during API call"}}
    except Exception as exc:
        result = {"ok": False, "error": {"message": str(exc)}}
    elapsed = (time.perf_counter() - started) * 1000
    if trace_api:
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
    attach_agent_ai_brief(
        report,
        "market",
        task=task,
        context={"symbol": symbol, "tick_analysis": tick_analysis, "candle_result": candle_result},
        events=events,
        writer=writer,
    )
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
    attach_agent_ai_brief(
        plan,
        "strategy",
        task=task,
        context={"symbol": symbol, "market": market, "local_plan": plan},
        events=events,
        writer=writer,
    )
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
        attach_agent_ai_brief(
            report,
            "risk",
            task=task,
            context={"symbol": symbol, "amount": amount, "risk_status": report},
            events=events,
            writer=writer,
        )
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
    attach_agent_ai_brief(
        report,
        "risk",
        task=task,
        context={"symbol": symbol, "amount": amount, "account_result": account_result, "risk_status": report},
        events=events,
        writer=writer,
    )
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
    attach_agent_ai_brief(
        report,
        "compliance",
        task=task,
        context={"amount": amount, "contract_type": contract_type, "local_compliance": report},
        events=events,
        writer=writer,
    )
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
    attach_agent_ai_brief(
        report,
        "chart",
        task=task,
        context={"symbol": symbol, "granularity": granularity, "count": count, "chart_result": result},
        events=events,
        writer=writer,
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
    attach_agent_ai_brief(
        report,
        "report",
        task=task,
        context={"events": [event.line() for event in events], "report": report},
        events=events,
        writer=writer,
    )
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
    contract_id: int | None = None,
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
        attach_agent_ai_brief(
            report,
            "execution",
            task=task,
            context={
                "symbol": symbol,
                "amount": amount,
                "contract_type": contract_type,
                "duration": duration,
                "duration_unit": duration_unit,
                "execution_status": report,
            },
            events=events,
            writer=writer,
        )
        remember_agent_report("execution", report)
        return report

    close_intent = has_close_intent(task)
    contract_id = contract_id or extract_contract_id(task)
    pending = {
        "action": "close_open_contract" if close_intent else "execute_simulated_trade",
        "symbol": symbol,
        "amount": float(amount),
        "contract_type": contract_type,
        "duration": int(duration),
        "duration_unit": duration_unit,
        "contract_id": contract_id,
        "allow_live": bool(st.session_state.allow_live_execution),
    }
    if st.session_state.require_trade_confirmation and not st.session_state.confirm_next_trade:
        st.session_state.pending_trade = pending
        report = {
            "role": "Execution Trader",
            "ok": False,
            "status": "blocked",
            "reason": "pending_human_confirmation",
            "pending_trade": pending,
        }
        append_team_event(events, "执行交易员", "经理", "已拦截写操作：需要老板在侧边栏确认下一笔订单。", writer)
        attach_agent_ai_brief(
            report,
            "execution",
            task=task,
            context={"pending_trade": pending, "execution_status": report},
            events=events,
            writer=writer,
        )
        remember_agent_report("execution", report)
        return report

    account_result = call_deriv_tool(
        "check_account_status",
        check_account_status(st.session_state.deriv_token),
        {"api_token": st.session_state.deriv_token},
        writer,
    )
    account_ok = bool(account_result.get("ok"))
    account_type = ((account_result.get("data") or {}).get("account_type") or "unknown")
    if account_type == "live" and not st.session_state.allow_live_execution:
        report = {
            "role": "Execution Trader",
            "ok": False,
            "status": "blocked",
            "reason": "live_account_blocked",
            "account": account_result.get("data"),
        }
        append_team_event(events, "执行交易员", "经理", "已拦截 live 账户写操作：默认只允许 demo token。", writer)
        attach_agent_ai_brief(
            report,
            "execution",
            task=task,
            context={"pending_trade": pending, "account_result": account_result, "execution_status": report},
            events=events,
            writer=writer,
        )
        remember_agent_report("execution", report)
        return report

    if close_intent:
        if not contract_id:
            status_result = call_deriv_tool(
                "get_open_contract_status",
                get_open_contract_status(st.session_state.deriv_token, None),
                {"api_token": st.session_state.deriv_token, "contract_id": None},
                writer,
            )
            report = {
                "role": "Execution Trader",
                "ok": False,
                "status": "blocked",
                "reason": "missing_contract_id_for_close",
                "account_checked": account_ok,
                "account": account_result.get("data"),
                "open_contract_status": status_result.get("data"),
            }
            append_team_event(events, "执行交易员", "经理", "平仓需要明确 contract_id。我已读取持仓状态供老板选择。", writer)
            attach_agent_ai_brief(
                report,
                "execution",
                task=task,
                context={"pending_trade": pending, "account_result": account_result, "open_contract_status": status_result},
                events=events,
                writer=writer,
            )
            remember_agent_report("execution", report)
            return report
        receipt_result = call_deriv_tool(
            "close_open_contract",
            close_open_contract(
                st.session_state.deriv_token,
                contract_id,
                0.0,
                bool(st.session_state.allow_live_execution),
            ),
            {
                "api_token": st.session_state.deriv_token,
                "contract_id": contract_id,
                "price": 0.0,
                "allow_live": bool(st.session_state.allow_live_execution),
            },
            writer,
        )
    else:
        receipt_result = call_deriv_tool(
            "execute_simulated_trade",
            execute_simulated_trade(
                st.session_state.deriv_token,
                symbol,
                float(amount),
                contract_type,
                int(duration),
                duration_unit,
                bool(st.session_state.allow_live_execution),
            ),
            {
                "api_token": st.session_state.deriv_token,
                "symbol": symbol,
                "amount": float(amount),
                "contract_type": contract_type,
                "duration": int(duration),
                "duration_unit": duration_unit,
                "allow_live": bool(st.session_state.allow_live_execution),
            },
            writer,
        )
    st.session_state.confirm_next_trade = False
    st.session_state.pending_trade = None
    if receipt_result.get("ok"):
        st.session_state.last_trade_receipt = receipt_result
        receipt = ((receipt_result.get("data") or {}).get("receipt") or (receipt_result.get("data") or {}).get("sell") or {})
        report = {
            "role": "Execution Trader",
            "ok": True,
            "account_checked": account_ok,
            "account": account_result.get("data"),
            "receipt": receipt,
            "action": pending["action"],
        }
        append_team_event(
            events,
            "执行交易员",
            "经理",
            (
                ("平仓成功，" if close_intent else "下单成功，")
                +
                f"合同ID: {receipt.get('contract_id') or contract_id}，"
                f"成交价: {receipt.get('purchase_price') or receipt.get('sold_for') or receipt.get('sell_price')} "
                f"{receipt.get('currency', '')}。"
            ),
            writer,
        )
        attach_agent_ai_brief(
            report,
            "execution",
            task=task,
            context={"pending_trade": pending, "account_result": account_result, "receipt_result": receipt_result},
            events=events,
            writer=writer,
        )
        remember_agent_report("execution", report)
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
    attach_agent_ai_brief(
        report,
        "execution",
        task=task,
        context={"pending_trade": pending, "account_result": account_result, "receipt_result": receipt_result},
        events=events,
        writer=writer,
    )
    remember_agent_report("execution", report)
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
        contract_id=arguments.get("contract_id"),
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
            {"role": "system", "content": manager_system_prompt()},
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
                system=manager_system_prompt(),
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
    pending = {
        "action": "execute_simulated_trade",
        "symbol": params["symbol"],
        "amount": float(params["amount"]),
        "contract_type": params["contract_type"],
        "duration": int(params["duration"]),
        "duration_unit": params["duration_unit"],
        "contract_id": None,
        "allow_live": bool(st.session_state.allow_live_execution),
        "source": "closed_loop",
    }
    if st.session_state.require_trade_confirmation and not st.session_state.confirm_next_trade:
        st.session_state.pending_trade = pending
        result = {
            "ok": False,
            "error": {
                "message": "写操作已进入待确认队列。请先确认下一笔模拟盘订单。",
                "reason": "pending_human_confirmation",
                "pending_trade": pending,
            },
        }
        log.append("   order_status=WAITING_CONFIRMATION")
        log.append("   reason=pending_human_confirmation")
        publish_agent_log(log)
        return result, summarize_result(plan, result)

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
            bool(st.session_state.allow_live_execution),
        ),
        {
            "api_token": st.session_state.deriv_token,
            "symbol": params["symbol"],
            "amount": params["amount"],
            "contract_type": params["contract_type"],
            "duration": params["duration"],
            "duration_unit": params["duration_unit"],
            "allow_live": bool(st.session_state.allow_live_execution),
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


def global_status_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    advisor = state.get("last_advisor_result") or {}
    pending_trade = state.get("pending_trade")
    symbol = (
        advisor.get("symbol")
        or (((state.get("last_tick") or {}).get("data") or {}).get("symbol"))
        or state.get("advisor_symbol")
        or DEFAULT_SYMBOL
    )
    entry_price = advisor.get("entry_price")
    return {
        "symbol": symbol,
        "advisor_stance": advisor.get("stance") or "WAIT",
        "advisor_confidence": float(advisor.get("confidence") or 0),
        "entry_price": entry_price,
        "api_calls": len(state.get("api_trace") or []),
        "sync_version": int(state.get("sync_version") or 0),
        "pending_trade": bool(pending_trade),
    }


def timestamp_age_seconds(value: Any, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        parsed = pd.to_datetime(value, utc=True).to_pydatetime()
    except (TypeError, ValueError):
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return round(max(0.0, (current - parsed).total_seconds()), 1)


def freshness_item(value: Any, max_age_seconds: int, *, now: datetime | None = None) -> dict[str, Any]:
    age = timestamp_age_seconds(value, now=now)
    if age is None:
        return {"age_seconds": None, "status": "missing", "fresh": False}
    fresh = age <= max_age_seconds
    return {
        "age_seconds": age,
        "status": "fresh" if fresh else "stale",
        "fresh": fresh,
    }


def freshness_snapshot(state: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    tick = state.get("last_tick") or {}
    tick_data = tick.get("data") or {}
    tick_payload = tick_data.get("tick") or {}
    snapshots = list(state.get("chart_snapshots") or [])
    latest_chart = snapshots[0] if snapshots else {}
    chart_timestamp = (
        latest_chart.get("created_at")
        or ((state.get("last_candles") or {}).get("timestamp"))
    )
    advisor = state.get("last_advisor_result") or {}
    items = {
        "tick": freshness_item(
            tick_payload.get("timestamp") or tick.get("timestamp"),
            FRESHNESS_LIMITS_SECONDS["tick"],
            now=now,
        ),
        "chart": freshness_item(
            chart_timestamp,
            FRESHNESS_LIMITS_SECONDS["chart"],
            now=now,
        ),
        "advisor": freshness_item(
            advisor.get("created_at"),
            FRESHNESS_LIMITS_SECONDS["advisor"],
            now=now,
        ),
    }
    known_count = sum(1 for item in items.values() if item["status"] != "missing")
    fresh_count = sum(1 for item in items.values() if item["fresh"])
    stale_count = sum(1 for item in items.values() if item["status"] == "stale")
    return {
        "items": items,
        "known_count": known_count,
        "fresh_count": fresh_count,
        "stale_count": stale_count,
        "missing_count": len(items) - known_count,
        "ok": known_count > 0 and stale_count == 0,
    }


def render_global_status_bar() -> None:
    snapshot = global_status_snapshot(dict(st.session_state))
    freshness = freshness_snapshot(dict(st.session_state))
    entry = snapshot.get("entry_price")
    entry_text = f"{float(entry):.5g}" if entry else t("status_none")
    confidence = float(snapshot.get("advisor_confidence") or 0)
    pending_text = t("status_yes") if snapshot.get("pending_trade") else t("status_none")
    freshness_text = (
        t("status_none")
        if not freshness["known_count"]
        else f'{freshness["fresh_count"]}/{freshness["known_count"]}'
    )
    st.markdown(
        f"""
        <div class="global-status">
          <div class="status-cell"><span>{html.escape(t("status_symbol"))}</span><strong>{html.escape(str(snapshot["symbol"]))}</strong></div>
          <div class="status-cell"><span>{html.escape(t("status_advisor"))}</span><strong>{html.escape(str(snapshot["advisor_stance"]))} · {confidence:.0%}</strong></div>
          <div class="status-cell"><span>{html.escape(t("status_entry"))}</span><strong>{html.escape(entry_text)}</strong></div>
          <div class="status-cell {'attention' if freshness.get('stale_count') else ''}"><span>{html.escape(t("status_freshness"))}</span><strong>{html.escape(freshness_text)}</strong></div>
          <div class="status-cell"><span>{html.escape(t("status_api_calls"))}</span><strong>{int(snapshot["api_calls"])}</strong></div>
          <div class="status-cell"><span>{html.escape(t("status_sync"))}</span><strong>{int(snapshot["sync_version"])}</strong></div>
          <div class="status-cell {'attention' if snapshot.get('pending_trade') else ''}"><span>{html.escape(t("status_pending"))}</span><strong>{html.escape(pending_text)}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def safety_gate_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    has_token = bool(str(state.get("deriv_token") or "").strip())
    requires_confirmation = bool(state.get("require_trade_confirmation"))
    confirmed_next = bool(state.get("confirm_next_trade"))
    live_enabled = bool(state.get("allow_live_execution"))
    pending_trade = bool(state.get("pending_trade"))
    confirmation_ready = (not requires_confirmation) or confirmed_next
    freshness = freshness_snapshot(state)
    return {
        "has_token": has_token,
        "requires_confirmation": requires_confirmation,
        "confirmed_next": confirmed_next,
        "confirmation_ready": confirmation_ready,
        "live_enabled": live_enabled,
        "pending_trade": pending_trade,
        "data_freshness_ok": bool(freshness["ok"]),
        "fresh_count": freshness["fresh_count"],
        "known_freshness_count": freshness["known_count"],
        "stale_count": freshness["stale_count"],
        "write_ready": has_token and confirmation_ready and not pending_trade,
    }


def render_safety_gate_panel() -> None:
    snapshot = safety_gate_snapshot(dict(st.session_state))
    token_state = t("safety_ready") if snapshot["has_token"] else t("safety_blocked")
    confirmation_state = (
        t("safety_ready")
        if snapshot["confirmation_ready"]
        else t("safety_required")
    )
    live_state = t("safety_enabled") if snapshot["live_enabled"] else t("safety_disabled")
    pending_state = t("status_yes") if snapshot["pending_trade"] else t("status_none")
    freshness_state = (
        t("safety_ready")
        if snapshot["data_freshness_ok"]
        else f'{snapshot["fresh_count"]}/{snapshot["known_freshness_count"]}'
    )
    cells = [
        (t("safety_token"), token_state, snapshot["has_token"]),
        (t("safety_confirmation"), confirmation_state, snapshot["confirmation_ready"]),
        (t("safety_freshness"), freshness_state, snapshot["data_freshness_ok"]),
        (t("safety_live"), live_state, not snapshot["live_enabled"]),
        (t("safety_pending_order"), pending_state, not snapshot["pending_trade"]),
    ]
    html_cells = []
    for label, value, ok in cells:
        html_cells.append(
            f"""
            <div class="safety-cell {'ok' if ok else 'warn'}">
              <span>{html.escape(label)}</span>
              <strong>{html.escape(value)}</strong>
            </div>
            """.strip()
        )
    st.markdown(
        f"""
        <div class="safety-panel">
          <div class="safety-title">{html.escape(t("safety_gate_panel"))}</div>
          <div class="safety-grid">{''.join(html_cells)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def advisor_trade_alignment(pending: dict[str, Any], advisor: dict[str, Any] | None) -> str:
    action = str(pending.get("action") or "")
    if action == "close_open_contract":
        return "close_action"
    if not advisor:
        return "no_advisor"
    pending_symbol = str(pending.get("symbol") or "")
    advisor_symbol = str(advisor.get("symbol") or "")
    if pending_symbol and advisor_symbol and pending_symbol != advisor_symbol:
        return "symbol_mismatch"
    advisor_stance = str(advisor.get("stance") or "WAIT").upper()
    direction = str(pending.get("contract_type") or "").upper()
    if advisor_stance == "WAIT":
        return "advisor_wait"
    if advisor_stance and direction and advisor_stance == direction:
        return "aligned"
    if advisor_stance in {"CALL", "PUT"} and direction in {"CALL", "PUT"}:
        return "direction_conflict"
    return "unknown"


def pending_trade_summary(
    pending: dict[str, Any] | None,
    advisor: dict[str, Any] | None = None,
    freshness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not pending:
        return {"has_pending_trade": False, "flags": []}
    action = str(pending.get("action") or "")
    direction = str(pending.get("contract_type") or "").upper()
    amount = pending.get("amount")
    duration = pending.get("duration")
    duration_unit = str(pending.get("duration_unit") or "")
    alignment = advisor_trade_alignment(pending, advisor)
    flags: list[str] = []
    if not pending.get("symbol") and action != "close_open_contract":
        flags.append("missing_symbol")
    if action != "close_open_contract" and direction not in {"CALL", "PUT"}:
        flags.append("missing_direction")
    try:
        amount_value = float(amount) if amount is not None else 0.0
    except (TypeError, ValueError):
        amount_value = 0.0
    if action != "close_open_contract" and amount_value <= 0:
        flags.append("missing_amount")
    try:
        duration_value = int(duration) if duration is not None else 0
    except (TypeError, ValueError):
        duration_value = 0
    if action != "close_open_contract" and duration_value <= 0:
        flags.append("missing_duration")
    if pending.get("allow_live"):
        flags.append("live_execution")
    if alignment in {"symbol_mismatch", "advisor_wait", "direction_conflict"}:
        flags.append(alignment)
    stale_count = int((freshness or {}).get("stale_count") or 0)
    if stale_count:
        flags.append("stale_data")
    return {
        "has_pending_trade": True,
        "action": action or "unknown",
        "symbol": pending.get("symbol"),
        "direction": direction or None,
        "amount": amount_value if amount is not None else None,
        "duration": f"{duration_value}{duration_unit}" if duration_value and duration_unit else None,
        "allow_live": bool(pending.get("allow_live")),
        "advisor_alignment": alignment,
        "fresh_count": int((freshness or {}).get("fresh_count") or 0),
        "known_freshness_count": int((freshness or {}).get("known_count") or 0),
        "stale_count": stale_count,
        "flags": flags,
    }


def advisor_trade_draft(
    advisor: dict[str, Any] | None,
    *,
    amount: float = 1.0,
    duration: int = 5,
    duration_unit: str = "t",
    allow_live: bool = False,
) -> dict[str, Any]:
    if not advisor:
        return {"ok": False, "reason": "missing_advisor"}
    stance = str(advisor.get("stance") or "WAIT").upper()
    if stance not in {"CALL", "PUT"}:
        return {"ok": False, "reason": "advisor_wait", "stance": stance}
    symbol = normalize_deriv_symbol(str(advisor.get("symbol") or DEFAULT_SYMBOL))
    try:
        amount_value = float(amount)
    except (TypeError, ValueError):
        amount_value = 0.0
    try:
        duration_value = int(duration)
    except (TypeError, ValueError):
        duration_value = 0
    if amount_value <= 0:
        return {"ok": False, "reason": "invalid_amount", "stance": stance}
    if duration_value <= 0:
        return {"ok": False, "reason": "invalid_duration", "stance": stance}
    return {
        "ok": True,
        "pending_trade": {
            "action": "execute_simulated_trade",
            "symbol": symbol,
            "amount": amount_value,
            "contract_type": stance,
            "duration": duration_value,
            "duration_unit": duration_unit if duration_unit in {"t", "m", "h"} else "t",
            "contract_id": None,
            "allow_live": bool(allow_live),
            "source": "advisor_council",
            "advisor_created_at": advisor.get("created_at"),
            "advisor_confidence": float(advisor.get("confidence") or 0),
            "advisor_entry_price": advisor.get("entry_price"),
        },
    }


def advisor_audit_summary(advisor: dict[str, Any] | None) -> dict[str, Any] | None:
    if not advisor:
        return None
    return {
        "ok": bool(advisor.get("ok", True)),
        "created_at": advisor.get("created_at"),
        "symbol": advisor.get("symbol"),
        "stance": advisor.get("stance"),
        "confidence": advisor.get("confidence"),
        "entry_price": advisor.get("entry_price"),
        "runtime": advisor.get("runtime"),
        "source_count": advisor.get("source_count"),
        "vote_counts": advisor.get("vote_counts") or {},
        "consensus": advisor.get("consensus"),
    }


def execution_audit_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    advisor = state.get("last_advisor_result") or None
    freshness = freshness_snapshot(state)
    pending = state.get("pending_trade") or None
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "global_status": global_status_snapshot(state),
        "data_freshness": freshness,
        "safety_gate": safety_gate_snapshot(state),
        "pending_trade_summary": pending_trade_summary(pending, advisor, freshness),
        "pending_trade": pending,
        "advisor": advisor_audit_summary(advisor),
        "api_trace": list(state.get("api_trace") or [])[-20:],
        "runtime_events": list(state.get("runtime_events") or [])[-30:],
        "chart_snapshot_count": len(state.get("chart_snapshots") or []),
        "team_event_count": len(state.get("team_events") or []),
    }


def render_audit_export_panel() -> None:
    st.markdown(f"#### {t('audit_export')}")
    st.caption(t("audit_export_caption"))
    snapshot = execution_audit_snapshot(dict(st.session_state))
    st.download_button(
        t("download_audit"),
        data=json.dumps(snapshot, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
        file_name=f"deriv-audit-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json",
        mime="application/json",
        width="stretch",
    )


def system_health_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    try:
        init_local_db()
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("SELECT 1").fetchone()
        checks["db"] = {"ok": True, "detail": str(DB_PATH)}
    except Exception as exc:
        checks["db"] = {"ok": False, "detail": str(exc)}

    try:
        build_advisor_langgraph()
        checks["langgraph"] = {"ok": True, "detail": "compiled"}
    except Exception as exc:
        checks["langgraph"] = {"ok": False, "detail": str(exc)}

    checks["token"] = {
        "ok": bool(str(state.get("deriv_token") or "").strip()),
        "detail": "configured" if state.get("deriv_token") else "missing",
    }
    checks["pending"] = {
        "ok": not bool(state.get("pending_trade")),
        "detail": "none" if not state.get("pending_trade") else "pending_trade",
    }
    freshness = freshness_snapshot(state)
    checks["freshness"] = {
        "ok": bool(freshness.get("ok")),
        "detail": f'{freshness.get("fresh_count", 0)}/{freshness.get("known_count", 0)} fresh',
    }
    required_ok = bool(checks["db"]["ok"] and checks["langgraph"]["ok"])
    attention = [
        key
        for key, item in checks.items()
        if key not in {"token", "freshness"} and not item["ok"]
    ]
    return {
        "ok": required_ok and not attention,
        "checks": checks,
        "attention": attention,
        "api_trace_count": len(state.get("api_trace") or []),
        "runtime_event_count": len(state.get("runtime_events") or []),
    }


def render_system_health_panel() -> None:
    health = system_health_snapshot(dict(st.session_state))
    st.markdown(f"#### {t('system_health')}")
    st.caption(t("system_health_caption"))
    cols = st.columns(5)
    checks = health["checks"]
    health_labels = {
        "db": t("health_db"),
        "langgraph": t("health_langgraph"),
        "token": t("health_token"),
        "pending": t("health_pending"),
        "freshness": t("status_freshness"),
    }
    for col, key in zip(cols, ["db", "langgraph", "token", "pending", "freshness"], strict=True):
        item = checks[key]
        col.metric(
            health_labels[key],
            t("health_ready") if item["ok"] else t("health_attention"),
            str(item["detail"]),
        )


def render_pending_trade_panel(*, show_raw: bool = True) -> None:
    pending = st.session_state.get("pending_trade")
    if not pending:
        return
    summary = pending_trade_summary(
        pending,
        st.session_state.get("last_advisor_result"),
        freshness_snapshot(dict(st.session_state)),
    )
    flags = summary.get("flags") or []
    flag_text = ", ".join(flags) if flags else t("safety_ready")
    freshness_text = (
        t("status_none")
        if not summary.get("known_freshness_count")
        else f'{summary.get("fresh_count")}/{summary.get("known_freshness_count")}'
    )
    st.markdown(
        f"""
        <div class="pending-panel">
          <div class="safety-title">{html.escape(t("pending_trade"))}</div>
          <div class="pending-grid">
            <div><span>{html.escape(t("pending_action"))}</span><strong>{html.escape(str(summary.get("action")))}</strong></div>
            <div><span>{html.escape(t("status_symbol"))}</span><strong>{html.escape(str(summary.get("symbol") or t("status_none")))}</strong></div>
            <div><span>{html.escape(t("pending_direction"))}</span><strong>{html.escape(str(summary.get("direction") or t("status_none")))}</strong></div>
            <div><span>{html.escape(t("pending_amount"))}</span><strong>{html.escape(str(summary.get("amount") or t("status_none")))}</strong></div>
            <div><span>{html.escape(t("pending_duration"))}</span><strong>{html.escape(str(summary.get("duration") or t("status_none")))}</strong></div>
            <div><span>{html.escape(t("pending_advisor_alignment"))}</span><strong>{html.escape(str(summary.get("advisor_alignment")))}</strong></div>
            <div><span>{html.escape(t("pending_freshness"))}</span><strong>{html.escape(freshness_text)}</strong></div>
            <div class="{'warn' if flags else 'ok'}"><span>{html.escape(t("pending_flags"))}</span><strong>{html.escape(flag_text)}</strong></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if show_raw:
        with st.expander(t("pending_raw_payload"), expanded=False):
            st.json(pending)


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
    is_en = current_lang() == "en"
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

    def edge_label(en: str, zh: str) -> str:
        return en if is_en else zh

    links = [
        {"source": "manager", "target": "strategy", "label": edge_label("DECOMPOSES", "拆解任务"), "strength": 0.95},
        {"source": "strategy", "target": "market", "label": edge_label("REQUESTS SIGNAL", "请求信号"), "strength": 0.86},
        {"source": "strategy", "target": "risk", "label": edge_label("SETS BOUNDARY", "设置边界"), "strength": 0.78},
        {"source": "risk", "target": "compliance", "label": edge_label("VALIDATES", "校验合规"), "strength": 0.84},
        {"source": "market", "target": "chart", "label": edge_label("VISUALIZES", "生成图表"), "strength": 0.76},
        {"source": "compliance", "target": "execution", "label": edge_label("APPROVES", "批准执行"), "strength": 0.88},
        {"source": "execution", "target": "report", "label": edge_label("RECEIPT TO", "回传回执"), "strength": 0.82},
        {"source": "report", "target": "manager", "label": edge_label("SUMMARIZES", "汇总复盘"), "strength": 0.72},
        {"source": "manager", "target": "market", "label": edge_label("ASSIGNS", "派给行情"), "strength": 0.7},
        {"source": "manager", "target": "execution", "label": edge_label("AUTHORIZES", "授权执行"), "strength": 0.7},
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
    graph_json = json.dumps(graph, ensure_ascii=True)
    title = html.escape(t("swarm_graph"))
    status_nodes = "Nodes" if is_en else "节点"
    status_links = "Relations" if is_en else "关系"
    status_layout = "Layout: Active" if is_en else "布局：运行中"
    details_title = "Node Details" if is_en else "节点详情"
    toolbar = {
        "refresh": "Refresh Layout" if is_en else "刷新布局",
        "reset": "Reset Zoom" if is_en else "重置缩放",
        "labels": "Show Edge Labels" if is_en else "显示边标签",
        "add": "Add Mock Node" if is_en else "新增模拟节点",
        "fit": "Fit View" if is_en else "适配视图",
    }
    component = f"""<!doctype html>
    <html lang="{html.escape('en' if is_en else 'zh-CN')}">
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    </head>
    <body>
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
        border: 1px solid rgba(38, 59, 52, .42);
        border-radius: 8px;
        background:
          linear-gradient(90deg, rgba(8,17,15,.07) 1px, transparent 1px),
          linear-gradient(0deg, rgba(8,17,15,.05) 1px, transparent 1px),
          linear-gradient(180deg, rgba(248,252,250,.97), rgba(236,245,241,.92));
        background-size: 22px 22px, 22px 22px, auto;
        color: #10221d;
        font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        box-shadow: 0 16px 44px rgba(0,0,0,.2);
        transform: translateZ(0);
      }}
      html, body {{
        margin: 0;
        width: 100%;
        height: 100%;
        background: transparent;
        font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
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
        border-radius: 8px;
        box-shadow: 0 10px 24px rgba(16,34,29,.1);
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
        box-shadow: 0 10px 24px rgba(16,34,29,.1);
        backdrop-filter: blur(12px);
        transition: transform .12s ease, background .12s ease;
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
        border-radius: 8px;
        box-shadow: 0 10px 24px rgba(16,34,29,.1);
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
        border-radius: 8px;
        box-shadow: 0 14px 38px rgba(16,34,29,.16);
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
        border-radius: 8px;
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
      const ui = {{
        selected: {json.dumps("Selected" if is_en else "选中", ensure_ascii=True)},
        hovered: {json.dumps("Hovered" if is_en else "悬停", ensure_ascii=True)},
        none: "-",
        memorySync: {json.dumps("Memory Sync: Local" if is_en else "本地同步：已连接", ensure_ascii=True)},
        directionOut: {json.dumps("OUT" if is_en else "发出", ensure_ascii=True)},
        directionIn: {json.dumps("IN" if is_en else "接收", ensure_ascii=True)},
        importance: {json.dumps("Importance" if is_en else "重要度", ensure_ascii=True)},
        confidence: {json.dumps("Confidence" if is_en else "置信度", ensure_ascii=True)},
        tags: {json.dumps("Tags" if is_en else "标签", ensure_ascii=True)},
        metadata: {json.dumps("Metadata" if is_en else "元数据", ensure_ascii=True)},
        connected: {json.dumps("Connected Relations" if is_en else "关联关系", ensure_ascii=True)},
        mockNode: {json.dumps("Mock Node" if is_en else "模拟节点", ensure_ascii=True)},
        mockDescription: {json.dumps("Simulated temporary graph node." if is_en else "临时模拟图谱节点。", ensure_ascii=True)},
        mockRelation: {json.dumps("SIMULATES" if is_en else "模拟连接", ensure_ascii=True)},
        typeLabels: {{
          system: {json.dumps("system" if is_en else "系统", ensure_ascii=True)},
          task: {json.dumps("task" if is_en else "任务", ensure_ascii=True)},
          risk: {json.dumps("risk" if is_en else "风控", ensure_ascii=True)},
          concept: {json.dumps("concept" if is_en else "概念", ensure_ascii=True)},
          api: {json.dumps("api" if is_en else "接口", ensure_ascii=True)}
        }}
      }};
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
      let lastStatusAt = 0;
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
      function roundedRect(x, y, w, h, r) {{
        const radius = Math.min(r, w / 2, h / 2);
        ctx.beginPath();
        ctx.moveTo(x + radius, y);
        ctx.arcTo(x + w, y, x + w, y + h, radius);
        ctx.arcTo(x + w, y + h, x, y + h, radius);
        ctx.arcTo(x, y + h, x, y, radius);
        ctx.arcTo(x, y, x + w, y, radius);
        ctx.closePath();
      }}
      function compactLabel(text, maxChars = 14) {{
        return text.length > maxChars ? text.slice(0, maxChars - 1) + '…' : text;
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
        if (alpha <= .052 && !dragging) return;
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
        alpha = Math.max(.045, alpha * .985);
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
          if (showLabels && active && zoom > .48) {{
            const mx = (l.source.x + l.target.x) / 2;
            const my = (l.source.y + l.target.y) / 2;
            ctx.font = `${{11 / zoom}}px "PingFang SC", "Microsoft YaHei", system-ui`;
            const edgeLabel = compactLabel(l.label, 18);
            const w = ctx.measureText(edgeLabel).width + 12 / zoom;
            ctx.globalAlpha = .58;
            ctx.fillStyle = 'rgba(255,255,255,.68)';
            roundedRect(mx - w / 2, my - 9 / zoom, w, 18 / zoom, 7 / zoom);
            ctx.fill();
            ctx.fillStyle = '#35544c';
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.globalAlpha = .72;
            ctx.fillText(edgeLabel, mx, my);
          }}
        }});

        nodes.forEach(n => {{
          const isFocus = focus && neighborhood.has(n.id);
          const isDim = focus && !isFocus;
          const pulse = (n === hovered || n === selected || n.id === 'manager') ? Math.sin(time * 2.8 + n.x * .01) * 1.6 : 0;
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
          ctx.font = `900 ${{13 / zoom}}px "PingFang SC", "Microsoft YaHei", system-ui`;
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText(n.code || n.label.slice(0, 2), n.x, n.y);
          if (zoom > .42) {{
            const label = compactLabel(n.label, n.id === 'manager' ? 18 : 12);
            ctx.font = `800 ${{12 / zoom}}px "PingFang SC", "Microsoft YaHei", system-ui`;
            const w = ctx.measureText(label).width + 16 / zoom;
            const h = 22 / zoom;
            const labelY = n.y + r + 15 / zoom;
            ctx.globalAlpha = isDim ? .18 : .74;
            ctx.fillStyle = 'rgba(255,255,255,.7)';
            roundedRect(n.x - w / 2, labelY - h / 2, w, h, 8 / zoom);
            ctx.fill();
            ctx.strokeStyle = 'rgba(255,255,255,.42)';
            ctx.lineWidth = 1 / zoom;
            ctx.stroke();
            ctx.fillStyle = '#17312b';
            ctx.globalAlpha = isDim ? .28 : .86;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText(label, n.x, labelY);
          }}
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
          .map(l => `<li><strong>${{l.source.id === node.id ? ui.directionOut : ui.directionIn}}</strong> ${{l.label}} · ${{l.source.id === node.id ? l.target.label : l.source.label}}</li>`).join('');
        panelBody.innerHTML = `
          <div class="kg-panel-type" style="background:${{node.color}}">${{ui.typeLabels[node.type] || node.type}}</div>
          <h3>${{node.label}}</h3>
          <div class="kg-panel-section">${{node.description || ''}}</div>
          <div class="kg-panel-section"><strong>${{ui.importance}}:</strong> ${{node.importance}}</div>
          <div class="kg-panel-section"><strong>${{ui.confidence}}:</strong> ${{node.confidence}}</div>
          <div class="kg-panel-section"><strong>${{ui.tags}}:</strong> ${{(node.tags || []).join(', ')}}</div>
          <div class="kg-panel-section"><strong>${{ui.metadata}}:</strong><br>${{Object.entries(node.metadata || {{}}).map(([k,v]) => `${{k}}: ${{v}}`).join('<br>')}}</div>
          <div class="kg-panel-section"><strong>${{ui.connected}}:</strong><ul>${{rels}}</ul></div>
        `;
        panel.classList.add('open');
      }}
      function renderLegend() {{
        const counts = {{}};
        nodes.forEach(n => counts[n.type] = (counts[n.type] || 0) + 1);
        legend.innerHTML = Object.entries(counts).map(([type, count]) =>
          `<div class="kg-legend-row"><span><i class="kg-dot" style="background:${{colors[type] || '#14b8a6'}}"></i>${{ui.typeLabels[type] || type}}</span><strong>${{count}}</strong></div>`
        ).join('');
      }}
      function renderStatus() {{
        const now = performance.now();
        if (now - lastStatusAt < 220) return;
        lastStatusAt = now;
        status.innerHTML = `<span>{status_nodes}: ${{nodes.length}}</span><span>{status_links}: ${{links.length}}</span><span>${{ui.selected}}: ${{selected ? selected.label : ui.none}}</span><span>${{ui.hovered}}: ${{hovered ? hovered.label : ui.none}}</span><span>{status_layout}</span><span>${{ui.memorySync}}</span><span>${{graph.status.updated}}</span>`;
      }}
      canvas.addEventListener('mousemove', e => {{
        if (dragging) {{ const p = world(e.clientX, e.clientY); dragging.x = p.x; dragging.y = p.y; dragging.vx = 0; dragging.vy = 0; alpha = .55; return; }}
        if (isPanning) {{ pan.x += e.clientX - last.x; pan.y += e.clientY - last.y; last = {{x:e.clientX,y:e.clientY}}; return; }}
        const nextHover = hit(e.clientX, e.clientY);
        if (nextHover !== hovered) {{
          hovered = nextHover;
          alpha = Math.max(alpha, .18);
        }}
      }});
      canvas.addEventListener('mousedown', e => {{
        const n = hit(e.clientX, e.clientY);
        alpha = Math.max(alpha, .45);
        if (n) {{ dragging = n; canvas.classList.add('dragging'); }}
        else {{ isPanning = true; last = {{x:e.clientX,y:e.clientY}}; }}
      }});
      window.addEventListener('mouseup', () => {{ dragging = null; isPanning = false; canvas.classList.remove('dragging'); }});
      canvas.addEventListener('click', e => {{ const n = hit(e.clientX, e.clientY); openPanel(n); }});
      canvas.addEventListener('wheel', e => {{
        e.preventDefault();
        const delta = e.deltaY > 0 ? .92 : 1.08;
        zoom = Math.max(.35, Math.min(2.8, zoom * delta));
        alpha = Math.max(alpha, .22);
      }}, {{ passive: false }});
      document.getElementById('kg-close').onclick = () => openPanel(null);
      document.getElementById('kg-labels').onchange = e => showLabels = e.target.checked;
      document.getElementById('kg-refresh').onclick = () => {{ alpha = 1; nodes.forEach(n => {{ n.vx += (Math.random()-.5)*6; n.vy += (Math.random()-.5)*6; }}); }};
      document.getElementById('kg-reset').onclick = () => {{ zoom = 1; pan = {{x:0,y:0}}; openPanel(null); }};
      document.getElementById('kg-fit').onclick = () => {{ zoom = .92; pan = {{x:0,y:0}}; }};
      document.getElementById('kg-add').onclick = () => {{
        const parent = nodes[Math.floor(Math.random() * nodes.length)];
        const id = 'mock-' + Math.random().toString(16).slice(2, 7);
        const node = {{ id, label: ui.mockNode + ' ' + nodes.length, code: 'MN', type: 'concept', description: ui.mockDescription, importance: .45, confidence: .74, color: '#06b6d4', tags: ['mock'], metadata: {{ status: 'simulated' }}, x: parent.x + 30, y: parent.y + 30, vx: 0, vy: 0, radius: 24 }};
        nodes.push(node); byId.set(id, node); links.push({{ source: parent, target: node, label: ui.mockRelation, strength: .55 }});
        alpha = 1; renderLegend();
      }};
      window.addEventListener('resize', resize);
      resize(); renderLegend(); draw();
    }})();
    </script>
    </body>
    </html>
    """
    encoded = base64.b64encode(component.encode("utf-8")).decode("ascii")
    st.iframe(f"data:text/html;charset=utf-8;base64,{encoded}", height=540, width="stretch")


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
    frame["local_timestamp"] = frame["timestamp"].dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
    frame["local_time"] = frame["timestamp"].dt.tz_convert(LOCAL_TZ).dt.strftime("%Y-%m-%d %H:%M:%S MYT")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
    frame["ma5"] = frame["close"].rolling(5).mean()
    frame["ma20"] = frame["close"].rolling(20).mean()
    return frame.reset_index(drop=True)


def chart_data_status(
    frame: pd.DataFrame,
    granularity: int,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if frame.empty or "timestamp" not in frame.columns:
        return {
            "ok": False,
            "fresh": False,
            "latest_utc": None,
            "latest_local": None,
            "age_seconds": None,
            "allowed_lag_seconds": max(int(granularity) * 3, 180),
        }
    latest_ts = pd.to_datetime(frame.iloc[-1]["timestamp"], utc=True)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age_seconds = max(0.0, (current - latest_ts.to_pydatetime()).total_seconds())
    allowed_lag = max(int(granularity) * 3, 180)
    return {
        "ok": True,
        "fresh": age_seconds <= allowed_lag,
        "latest_utc": latest_ts.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "latest_local": latest_ts.tz_convert(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S MYT"),
        "age_seconds": round(age_seconds, 1),
        "allowed_lag_seconds": allowed_lag,
    }


def local_time_label(value: Any, fmt: str = "%Y-%m-%d %H:%M:%S MYT") -> str:
    if not value:
        return ""
    try:
        timestamp = pd.to_datetime(value, utc=True)
    except (TypeError, ValueError):
        return str(value)
    return timestamp.tz_convert(LOCAL_TZ).strftime(fmt)


def normalize_close(frame: pd.DataFrame) -> pd.Series:
    first = frame["close"].dropna().iloc[0]
    if first == 0:
        return frame["close"]
    return frame["close"] / first * 100


def advisor_chart_overlay(symbol: str, advisor_result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not advisor_result:
        return None
    if str(advisor_result.get("symbol") or "") != str(symbol):
        return None
    entry_price = advisor_result.get("entry_price")
    try:
        price = float(entry_price)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price <= 0:
        return None
    stance = str(advisor_result.get("stance") or "WAIT").upper()
    colors = {"CALL": "#00b894", "PUT": "#f05f5f", "WAIT": "#f5b84b"}
    confidence = float(advisor_result.get("confidence") or 0)
    return {
        "symbol": symbol,
        "price": price,
        "stance": stance if stance in colors else "WAIT",
        "confidence": confidence,
        "color": colors.get(stance, colors["WAIT"]),
        "label": f"{stance if stance in colors else 'WAIT'} · {confidence:.0%}",
    }


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
    labels = [
        f"{idx} · {row.local_timestamp.strftime('%m-%d %H:%M')} MYT · close {row.close:.5g}"
        for idx, row in frame.iterrows()
    ]
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


def candle_result_count(result: dict[str, Any] | None) -> int:
    data = (result or {}).get("data") or {}
    try:
        returned_count = int(data.get("returned_count") or 0)
    except (TypeError, ValueError):
        returned_count = 0
    return max(returned_count, len(data.get("ohlcv") or []))


def fetch_and_store_candles(symbol: str, granularity: int, count: int, source: str) -> dict[str, Any]:
    result = fetch_compare_candles(symbol, granularity, count)
    if result.get("ok") and candle_result_count(result) > 0:
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
    status = chart_data_status(frame, granularity)

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

    status_cols = st.columns([0.25, 0.25, 0.25, 0.25])
    status_cols[0].metric(t("chart_last_candle"), status.get("latest_local") or "N/A")
    status_cols[1].metric(t("chart_data_age"), "N/A" if status.get("age_seconds") is None else f"{float(status['age_seconds']):.0f}s")
    status_cols[2].metric(t("chart_data_status"), t("chart_fresh") if status.get("fresh") else t("chart_stale"))
    status_cols[3].metric(t("chart_time_zone"), "MYT / UTC")
    st.caption(f"{t('chart_local_time_note')} {t('chart_refresh_hint')}")

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
            x=frame["local_timestamp"],
            open=frame["open"],
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            customdata=frame[["local_time", "utc_time"]],
            hovertemplate=(
                "%{customdata[0]}<br>"
                "%{customdata[1]}<br>"
                f"{symbol}: open=%{{open:.5f}}<br>"
                "high=%{high:.5f}<br>"
                "low=%{low:.5f}<br>"
                "close=%{close:.5f}<extra></extra>"
            ),
            increasing_line_color="#007f73",
            decreasing_line_color="#be3434",
            increasing_fillcolor="#007f73",
            decreasing_fillcolor="#be3434",
            name=symbol,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=frame["local_timestamp"],
            y=frame["ma5"],
            mode="lines",
            line=dict(color="#d89b24", width=1.5),
            name="MA5",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=frame["local_timestamp"],
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
                x=compare_frame["local_timestamp"],
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
    overlay = advisor_chart_overlay(symbol, st.session_state.get("last_advisor_result"))
    if overlay:
        fig.add_hline(
            y=overlay["price"],
            line_width=2,
            line_dash="dash",
            line_color=overlay["color"],
            annotation_text=f"{t('chart_advisor_overlay')} {overlay['label']} · {overlay['price']:.5g}",
            annotation_position="left",
        )
        fig.add_trace(
            go.Scatter(
                x=[frame.iloc[-1]["local_timestamp"]],
                y=[overlay["price"]],
                mode="markers+text",
                marker=dict(size=12, color=overlay["color"], line=dict(color="#ffffff", width=1)),
                text=[overlay["stance"]],
                textposition="top center",
                name=t("chart_advisor_overlay"),
                hovertemplate=(
                    f"{t('chart_advisor_overlay')}<br>"
                    "stance=%{text}<br>"
                    "entry=%{y:.5f}<extra></extra>"
                ),
            )
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

    with st.expander(t("measure_data"), expanded=False):
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


def render_chart_loader_controls() -> None:
    current_symbol = selected_chart_symbol(
        str(st.session_state.get("chart_loader_symbol", DEFAULT_SYMBOL)),
        "",
    )
    if current_symbol not in COMMON_DERIV_SYMBOLS:
        current_symbol = DEFAULT_SYMBOL
    current_granularity = int(st.session_state.get("chart_loader_granularity", DEFAULT_GRANULARITY) or DEFAULT_GRANULARITY)
    if current_granularity not in CHART_GRANULARITY_OPTIONS:
        current_granularity = DEFAULT_GRANULARITY
    current_count = int(st.session_state.get("chart_loader_count", 120) or 120)
    current_count = min(1000, max(20, current_count))

    st.session_state.chart_loader_symbol = current_symbol
    st.session_state.chart_loader_granularity = current_granularity
    st.session_state.chart_loader_count = current_count

    with st.container(border=True):
        st.subheader(t("chart_loader_title"))
        st.caption(t("chart_loader_caption"))
        cols = st.columns([0.25, 0.25, 0.25, 0.25])
        cols[0].selectbox(
            t("chart_symbol_select"),
            COMMON_DERIV_SYMBOLS,
            index=COMMON_DERIV_SYMBOLS.index(current_symbol),
            key="chart_loader_symbol",
        )
        cols[1].text_input(
            t("chart_custom_symbol"),
            key="chart_custom_symbol",
            placeholder=t("chart_custom_placeholder"),
        )
        cols[2].selectbox(
            t("chart_granularity"),
            CHART_GRANULARITY_OPTIONS,
            index=CHART_GRANULARITY_OPTIONS.index(current_granularity),
            key="chart_loader_granularity",
            format_func=chart_granularity_label,
        )
        cols[3].number_input(
            t("chart_candle_count"),
            min_value=20,
            max_value=1000,
            step=20,
            key="chart_loader_count",
        )

        if st.button(t("chart_load_selected"), type="primary", width="stretch"):
            symbol = selected_chart_symbol(
                str(st.session_state.chart_loader_symbol),
                str(st.session_state.chart_custom_symbol),
            )
            result = fetch_and_store_candles(
                symbol,
                int(st.session_state.chart_loader_granularity),
                int(st.session_state.chart_loader_count),
                source="chart_loader",
            )
            if result.get("ok") and candle_result_count(result) > 0:
                st.success(f"{t('chart_loaded')}: {symbol}")
            elif result.get("ok"):
                st.warning(t("chart_empty_info"))
            else:
                st.error(f"{t('chart_load_failed')}: {symbol}")
                st.json(result)


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
                f"{item.get('symbol')} · {item.get('granularity')}s · {local_time_label(item.get('created_at'), '%H:%M:%S MYT')}"
                for item in snapshots
            ]
        )
        for tab, item in zip(tabs, snapshots, strict=False):
            with tab:
                st.caption(
                    f"{t('snapshot_time')}: {local_time_label(item.get('created_at'))} · "
                    f"UTC={item.get('created_at')} · source={item.get('source')}"
                )
                render_trading_chart_workbench(item["result"])
    elif st.session_state.last_candles and st.session_state.last_candles.get("ok"):
        render_trading_chart_workbench(st.session_state.last_candles)
    else:
        with st.container(border=True):
            st.subheader(t("chart_workbench"))
            st.caption(t("no_chart_snapshots"))

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
                "contract_id": extract_contract_id(task),
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


def render_advisor_trade_draft_controls(result: dict[str, Any]) -> None:
    stance = str(result.get("stance") or "WAIT").upper()
    key_suffix = re.sub(r"[^A-Za-z0-9_]+", "_", str(result.get("created_at") or "latest"))
    with st.container(border=True):
        st.markdown(f"#### {t('advisor_trade_draft')}")
        st.caption(t("advisor_trade_draft_caption"))
        controls = st.columns([0.28, 0.28, 0.24, 0.2])
        amount = controls[0].number_input(
            t("advisor_trade_amount"),
            min_value=0.35,
            max_value=1000.0,
            value=1.0,
            step=0.5,
            key=f"advisor_trade_amount_{key_suffix}",
        )
        duration = controls[1].number_input(
            t("advisor_trade_duration"),
            min_value=1,
            max_value=60,
            value=5,
            step=1,
            key=f"advisor_trade_duration_{key_suffix}",
        )
        duration_unit = controls[2].selectbox(
            "Unit",
            ["t", "m", "h"],
            index=0,
            key=f"advisor_trade_unit_{key_suffix}",
        )
        disabled = stance not in {"CALL", "PUT"}
        if controls[3].button(
            t("advisor_trade_draft"),
            type="primary",
            width="stretch",
            disabled=disabled,
            key=f"advisor_trade_button_{key_suffix}",
        ):
            draft = advisor_trade_draft(
                result,
                amount=float(amount),
                duration=int(duration),
                duration_unit=str(duration_unit),
                allow_live=bool(st.session_state.allow_live_execution),
            )
            if draft.get("ok"):
                st.session_state.pending_trade = draft["pending_trade"]
                st.session_state.active_page = "trading"
                st.success(t("advisor_trade_created"))
                st.rerun()
            else:
                st.warning(t("advisor_trade_wait_blocked"))
        if disabled:
            st.info(t("advisor_trade_wait_blocked"))


def render_advisor_result(result: dict[str, Any]) -> None:
    st.markdown(
        f"""
        <div class="advisor-result">
          <strong>{html.escape(t("advisor_consensus"))} · {html.escape(str(result.get("stance", "WAIT")))}</strong>
          <div class="advisor-copy">{html.escape(str(result.get("consensus") or ""))}</div>
          <div class="advisor-copy">{html.escape(t("advisor_disclaimer"))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(5)
    cols[0].metric(t("advisor_confidence"), f"{float(result.get('confidence') or 0):.0%}")
    cols[1].metric(t("advisor_elapsed"), f"{float(result.get('elapsed_ms') or 0) / 1000:.1f}s")
    cols[2].metric(t("advisor_sources"), int(result.get("source_count") or 0))
    entry_price = result.get("entry_price")
    cols[3].metric(t("advisor_entry_price"), f"{float(entry_price):.5g}" if entry_price else "N/A")
    cols[4].metric("Runtime", str(result.get("runtime") or "local"))
    st.caption(f"Votes: `{json.dumps(result.get('vote_counts') or {}, ensure_ascii=False)}`")
    render_advisor_trade_draft_controls(result)

    opinions = result.get("opinions") or []
    cards = []
    for opinion in opinions:
        specs = advisor_specs()
        spec = next((item for item in specs if item["id"] == opinion.get("advisor_id")), specs[0])
        cards.append(
            f"""
<div class="advisor-card">
  <div class="advisor-card-top">
    <div class="advisor-code" style="border-color:{html.escape(spec['color'])};">{html.escape(spec['code'])}</div>
    <div>
      <div class="advisor-name">{html.escape(str(opinion.get("name") or ""))}</div>
      <div class="advisor-role">{html.escape(str(opinion.get("role") or ""))}</div>
    </div>
  </div>
  <span class="advisor-stance">{html.escape(str(opinion.get("stance") or "WAIT"))}</span>
  <div class="advisor-copy">{html.escape(str(opinion.get("rationale") or ""))}</div>
  <div class="advisor-copy"><strong>Invalidation:</strong> {html.escape(str(opinion.get("invalidation") or ""))}</div>
</div>
            """.strip()
        )
    if cards:
        st.markdown(f'<div class="advisor-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

    with st.expander(t("advisor_sources"), expanded=bool(result.get("sources"))):
        sources = result.get("sources") or []
        if sources:
            st.dataframe(
                [
                    {
                        "title": item.get("title"),
                        "source": item.get("source"),
                        "published": item.get("published"),
                        "url": item.get("url"),
                    }
                    for item in sources
                ],
                width="stretch",
                height=240,
                column_config={"url": st.column_config.LinkColumn("url")},
            )
        else:
            st.caption(t("advisor_no_sources"))

    with st.expander(t("advisor_transcript"), expanded=False):
        st.json(
            {
                "question": result.get("question"),
                "symbol": result.get("symbol"),
                "market": result.get("market"),
                "news_signal": result.get("news_signal"),
                "opinions": result.get("opinions"),
                "vote_counts": result.get("vote_counts"),
            }
        )
    st.download_button(
        t("advisor_download"),
        data=json.dumps(result, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
        file_name=f"advisor-council-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json",
        mime="application/json",
        width="stretch",
    )


def fetch_latest_price_for_evaluation(symbol: str) -> float | None:
    result = call_deriv_tool(
        "get_market_ticks",
        get_market_ticks(symbol, False),
        {"symbol": symbol, "subscribe": False, "advisor_evaluation": True},
    )
    if not result.get("ok"):
        return None
    value = (((result.get("data") or {}).get("tick") or {}).get("quote"))
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


def fetch_candles_for_evaluation(symbol: str, granularity: int = 60, count: int = 120) -> pd.DataFrame:
    result = call_deriv_tool(
        "get_historical_candles",
        get_historical_candles(symbol, granularity, count),
        {
            "symbol": symbol,
            "granularity": granularity,
            "count": count,
            "advisor_evaluation": True,
        },
    )
    return candles_frame_from_result(result)


def evaluate_recent_advisors(limit: int = 12) -> list[dict[str, Any]]:
    records = load_advisor_run_records(limit)
    price_cache: dict[str, float | None] = {}
    candle_cache: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, Any]] = []
    for record in records:
        result = record.get("result") or {}
        symbol = str(result.get("symbol") or record.get("symbol") or DEFAULT_SYMBOL)
        if symbol not in price_cache:
            price_cache[symbol] = fetch_latest_price_for_evaluation(symbol)
        if symbol not in candle_cache:
            candle_cache[symbol] = fetch_candles_for_evaluation(symbol)
        entry = result.get("entry_price")
        if entry is None:
            entry = advisor_entry_price(dict(result.get("market") or {}))
        evaluation = evaluate_advisor_outcome(
            str(result.get("stance") or "WAIT"),
            entry,
            price_cache[symbol],
            float(result.get("confidence") or record.get("confidence") or 0),
        )
        future_closes = future_closes_after_created_at(
            candle_cache[symbol],
            str(result.get("created_at") or record.get("created_at") or ""),
            10,
        )
        created_at = str(result.get("created_at") or record.get("created_at") or "")
        readiness = advisor_horizon_readiness(created_at)
        horizon_evaluation = evaluate_advisor_horizons(
            str(result.get("stance") or "WAIT"),
            entry,
            future_closes,
            float(result.get("confidence") or record.get("confidence") or 0),
        )
        horizons = horizon_evaluation.get("horizons") or {}
        rows.append(
            {
                "id": record.get("id"),
                "created_at": record.get("created_at"),
                "symbol": symbol,
                "stance": evaluation["stance"],
                "confidence": evaluation["confidence"],
                "entry_price": evaluation["entry_price"],
                "exit_price": evaluation["exit_price"],
                "return_pct": evaluation["return_pct"],
                "paper_return_pct": evaluation["paper_return_pct"],
                "status": evaluation["status"],
                "outcome": evaluation["outcome"],
                "score": evaluation["score"],
                "horizon_status": horizon_evaluation["status"],
                "horizon_average_score": horizon_evaluation["average_score"],
                "horizon_1m": (horizons.get("1m") or {}).get("paper_return_pct"),
                "horizon_5m": (horizons.get("5m") or {}).get("paper_return_pct"),
                "horizon_10m": (horizons.get("10m") or {}).get("paper_return_pct"),
                "horizon_outcome_1m": (horizons.get("1m") or {}).get("outcome"),
                "horizon_outcome_5m": (horizons.get("5m") or {}).get("outcome"),
                "horizon_outcome_10m": (horizons.get("10m") or {}).get("outcome"),
                "ready_horizons": ",".join(readiness.get("ready") or []),
                "pending_horizons": ",".join(readiness.get("pending") or []),
                "age_seconds": readiness.get("age_seconds"),
                "evaluation_ready": advisor_evaluation_ready(created_at, entry),
                "question": record.get("question"),
            }
        )
    return rows


def render_advisor_evaluation_panel() -> None:
    with st.expander(t("advisor_evaluation"), expanded=False):
        st.caption(t("advisor_evaluation_caption"))
        if st.button(t("advisor_mark_recent"), width="stretch"):
            st.session_state.advisor_evaluations = evaluate_recent_advisors(12)

        evaluations = list(st.session_state.get("advisor_evaluations") or [])
        if not evaluations:
            st.caption(t("advisor_no_evaluations"))
            return

        summary = summarize_advisor_evaluations(evaluations)
        horizon_scores = [
            float(item["horizon_average_score"])
            for item in evaluations
            if item.get("horizon_average_score") is not None
        ]
        average_horizon_score = round(sum(horizon_scores) / len(horizon_scores), 3) if horizon_scores else None
        cols = st.columns(5)
        accuracy = summary.get("direction_accuracy")
        avg_return = summary.get("average_paper_return_pct")
        avg_score = summary.get("average_score")
        cols[0].metric(t("advisor_outcome"), int(summary.get("evaluated_count") or 0))
        cols[1].metric(
            t("advisor_direction_accuracy"),
            "N/A" if accuracy is None else f"{float(accuracy):.0%}",
        )
        cols[2].metric(
            t("advisor_paper_return"),
            "N/A" if avg_return is None else f"{float(avg_return):+.3f}%",
        )
        cols[3].metric("Score", "N/A" if avg_score is None else f"{float(avg_score):.2f}")
        cols[4].metric(
            t("advisor_horizon_scores"),
            "N/A" if average_horizon_score is None else f"{average_horizon_score:.2f}",
        )

        st.dataframe(
            [
                {
                    "id": item.get("id"),
                    "time": str(item.get("created_at") or "")[:19],
                    "symbol": item.get("symbol"),
                    "stance": item.get("stance"),
                    "confidence": item.get("confidence"),
                    "entry": item.get("entry_price"),
                    "mark": item.get("exit_price"),
                    "return_pct": item.get("return_pct"),
                    "paper_return_pct": item.get("paper_return_pct"),
                    "status": item.get("status"),
                    "outcome": item.get("outcome"),
                    "1m_paper": item.get("horizon_1m"),
                    "1m_outcome": item.get("horizon_outcome_1m"),
                    "5m_paper": item.get("horizon_5m"),
                    "5m_outcome": item.get("horizon_outcome_5m"),
                    "10m_paper": item.get("horizon_10m"),
                    "10m_outcome": item.get("horizon_outcome_10m"),
                    "eval_ready": item.get("evaluation_ready"),
                    "ready": item.get("ready_horizons"),
                    "pending": item.get("pending_horizons"),
                    "question": item.get("question"),
                }
                for item in evaluations
            ],
            width="stretch",
            height=260,
        )
        performance = summarize_advisor_performance(evaluations)
        if performance:
            st.markdown(f"#### {t('advisor_performance')}")
            st.dataframe(
                performance,
                width="stretch",
                height=min(260, 56 + len(performance) * 36),
            )


def render_advisor_council() -> None:
    st.markdown(
        f"""
        <div class="advisor-room">
          <div class="advisor-room-head">
            <div>
              <div class="advisor-title">{html.escape(t("advisor_council"))}</div>
              <div class="advisor-caption">{html.escape(t("advisor_caption"))}</div>
            </div>
            <div class="advisor-deadline">FAST · WEB · COUNCIL</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    input_key = f"advisor_question_{st.session_state.advisor_prompt_nonce}"
    with st.form("advisor_council_form", border=True):
        question = st.text_area(
            t("advisor_question"),
            key=input_key,
            height=96,
            placeholder=t("advisor_placeholder"),
        )
        controls = st.columns([0.24, 0.24, 0.22, 0.16, 0.14])
        current_symbol = normalize_deriv_symbol(str(st.session_state.advisor_symbol))
        symbol_options = COMMON_DERIV_SYMBOLS + ["自定义"]
        current_symbol_index = (
            symbol_options.index(current_symbol)
            if current_symbol in symbol_options
            else len(symbol_options) - 1
        )
        selected_symbol = controls[0].selectbox(
            t("advisor_symbol"),
            symbol_options,
            index=current_symbol_index,
        )
        custom_symbol = controls[1].text_input(
            "Custom Symbol",
            value="" if selected_symbol != "自定义" else current_symbol,
            placeholder="例如 R_75 / BOOM1000 / frxEURUSD",
            disabled=selected_symbol != "自定义",
        )
        budget = controls[2].slider(
            t("advisor_time_budget"),
            min_value=4,
            max_value=25,
            value=int(st.session_state.advisor_time_budget),
            step=1,
        )
        use_web = controls[3].toggle(
            t("advisor_web_toggle"),
            value=bool(st.session_state.advisor_use_web),
        )
        submitted = controls[4].form_submit_button(t("advisor_start"), type="primary", width="stretch")

    if submitted:
        cleaned_question = question.strip()
        if not cleaned_question:
            st.warning(t("advisor_empty"))
            return
        chosen_symbol = custom_symbol if selected_symbol == "自定义" else selected_symbol
        st.session_state.advisor_symbol = normalize_deriv_symbol(
            chosen_symbol.strip() or extract_symbol(cleaned_question) or DEFAULT_SYMBOL
        )
        st.session_state.advisor_time_budget = int(budget)
        st.session_state.advisor_use_web = bool(use_web)
        with st.status(t("advisor_processing"), expanded=True) as status:

            def advisor_writer(line: str) -> None:
                st.write(line)

            result = run_advisor_council(
                cleaned_question,
                st.session_state.advisor_symbol,
                int(budget),
                bool(use_web),
                advisor_writer,
            )
            status.update(label=t("advisor_done"), state="complete", expanded=True)
        st.session_state.advisor_prompt_nonce += 1
        render_advisor_result(result)
        render_advisor_evaluation_panel()
        return

    if st.session_state.get("last_advisor_result"):
        st.markdown(f"#### {t('advisor_result')}")
        render_advisor_result(st.session_state.last_advisor_result)
    render_advisor_evaluation_panel()


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


PAGE_KEYS = ["advisor", "micro", "trading", "charts", "monitor"]
PAGE_NAV_CODES = {
    "advisor": "AD",
    "micro": "MI",
    "trading": "EX",
    "charts": "CH",
    "monitor": "MO",
}


def render_page_nav() -> str:
    current = st.session_state.get("active_page", "advisor")
    if current not in PAGE_KEYS:
        current = "advisor"
    current_label = t(f"page_{current}")
    st.markdown(
        f"""
        <div class="workspace-head">
          <div class="workspace-title">{html.escape(t('workspace'))}</div>
          <div class="workspace-route">Gateway / {html.escape(current_label)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    nav_cards = []
    for page_key in PAGE_KEYS:
        active = page_key == current
        state = "ACTIVE" if active else "READY"
        nav_cards.append(
            f"""
            <div class="nav-card {'active' if active else ''}">
              <div class="nav-top">
                <div class="nav-code">{html.escape(PAGE_NAV_CODES[page_key])}</div>
                <div class="nav-state">{state}</div>
              </div>
              <div class="nav-label">{html.escape(t(f'page_{page_key}'))}</div>
              <div class="nav-caption">{html.escape(t(f'page_{page_key}_caption'))}</div>
            </div>
            """.strip()
        )
    st.markdown(f'<div class="nav-grid">{"".join(nav_cards)}</div>', unsafe_allow_html=True)
    nav_cols = st.columns(len(PAGE_KEYS))
    for col, page_key in zip(nav_cols, PAGE_KEYS, strict=True):
        if col.button(
            t(f"page_{page_key}"),
            key=f"nav_{page_key}",
            type="primary" if page_key == current else "secondary",
            width="stretch",
        ):
            st.session_state.active_page = page_key
            st.rerun()
    selected = st.session_state.get("active_page", current)
    st.markdown(
        f"""
        <div class="page-context">
          <strong>{html.escape(t(f"page_{selected}"))}</strong>
          <span>{html.escape(t(f"page_{selected}_caption"))}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    return selected


def render_advisor_page() -> None:
    render_advisor_council()


def default_micro_prices() -> str:
    return "100,100.03,100.06,100.10,100.15,100.22,100.30,100.39,100.49,100.61,100.74,100.88,101.03,101.19,101.36,101.54"


def micro_price_frame_from_text(raw: str) -> pd.DataFrame:
    values: list[dict[str, float]] = []
    for chunk in re.split(r"[\n,，\s]+", raw.strip()):
        if not chunk:
            continue
        try:
            values.append({"close": float(chunk)})
        except ValueError:
            continue
    return normalize_price_frame(values)


def micro_budget_reason_label(reason: Any, *, lang: str | None = None) -> str:
    language = lang or current_lang()
    text = str(reason or "unknown")
    zh = {
        "within_budget": "未超预算",
        "single_trade_limit_exceeded": "单笔金额超过限制",
        "daily_budget_exceeded": "今日预算不足",
        "total_budget_exceeded": "总预算不足",
        "missing_amount": "缺少金额",
        "invalid_amount": "金额无效",
        "unknown": "未知",
    }
    en = {
        "within_budget": "Within budget",
        "single_trade_limit_exceeded": "Single-trade limit exceeded",
        "daily_budget_exceeded": "Daily budget exceeded",
        "total_budget_exceeded": "Total budget exceeded",
        "missing_amount": "Missing amount",
        "invalid_amount": "Invalid amount",
        "unknown": "Unknown",
    }
    labels = zh if language == "zh" else en
    return labels.get(text, text.replace("_", " "))


def micro_halt_reason_label(reason: Any, *, lang: str | None = None) -> str:
    language = lang or current_lang()
    text = str(reason or "none")
    zh = {
        "none": "无熔断",
        "max_consecutive_losses": "连续亏损熔断",
        "max_total_loss_amount": "累计亏损熔断",
        "max_drawdown_pct": "回撤熔断",
        "max_trade_count": "交易次数上限",
    }
    en = {
        "none": "No halt",
        "max_consecutive_losses": "Consecutive-loss halt",
        "max_total_loss_amount": "Total-loss halt",
        "max_drawdown_pct": "Drawdown halt",
        "max_trade_count": "Trade-count limit",
    }
    labels = zh if language == "zh" else en
    return labels.get(text, text.replace("_", " "))


def micro_action_label(action: Any, *, lang: str | None = None) -> str:
    language = lang or current_lang()
    text = str(action or "WAIT").upper()
    zh = {
        "CALL": "看涨",
        "PUT": "看跌",
        "WAIT": "等待",
        "BUY": "买入",
        "SELL": "卖出",
        "HOLD": "持有/等待",
    }
    en = {
        "CALL": "CALL",
        "PUT": "PUT",
        "WAIT": "Wait",
        "BUY": "Buy",
        "SELL": "Sell",
        "HOLD": "Hold",
    }
    labels = zh if language == "zh" else en
    label = labels.get(text, text)
    return f"{label} ({text})" if language == "zh" and text in {"CALL", "PUT"} else label


def micro_blocker_label(blocker: Any, *, lang: str | None = None) -> str:
    language = lang or current_lang()
    text = str(blocker or "")
    zh = {
        "weak_momentum": "动量太弱",
        "excess_volatility": "波动过高",
        "low_confidence": "置信度不足",
        "cost_edge_too_small": "扣除成本后优势太小",
        "single_trade_limit_exceeded": "单笔金额超过限制",
        "daily_budget_exceeded": "今日预算不足",
        "total_budget_exceeded": "总预算不足",
    }
    en = {
        "weak_momentum": "Weak momentum",
        "excess_volatility": "Excess volatility",
        "low_confidence": "Low confidence",
        "cost_edge_too_small": "Cost-adjusted edge too small",
        "single_trade_limit_exceeded": "Single-trade limit exceeded",
        "daily_budget_exceeded": "Daily budget exceeded",
        "total_budget_exceeded": "Total budget exceeded",
    }
    labels = zh if language == "zh" else en
    return labels.get(text, text.replace("_", " "))


def micro_operator_brief(
    decision: dict[str, Any],
    budget_check: dict[str, Any],
    backtest: dict[str, Any],
    frame: pd.DataFrame,
    *,
    lang: str | None = None,
    data_source: str = "manual",
    symbol: str = "",
) -> dict[str, Any]:
    language = lang or current_lang()
    action = str(decision.get("action") or "WAIT")
    confidence = float(decision.get("confidence") or 0.0)
    blockers = [str(item) for item in decision.get("blockers") or []]
    summary = backtest.get("summary") or {}
    trade_count = int(summary.get("trade_count") or 0)
    total_pnl = float(summary.get("total_pnl") or 0.0)
    win_rate = summary.get("win_rate")
    budget_ok = bool(budget_check.get("ok"))
    halt_reason = summary.get("halt_reason") or "none"
    is_live = data_source == "live"
    display_symbol = symbol or str(decision.get("symbol") or "")
    weak_backtest = bool(
        trade_count
        and (
            halt_reason != "none"
            or total_pnl <= 0
            or (win_rate is not None and float(win_rate) < 0.52)
        )
    )

    if not budget_ok:
        recommendation = "禁止交易" if language == "zh" else "Do Not Trade"
        headline = (
            "预算闸门已经阻止本轮交易，员工建议：不要开仓，不要继续加码。"
            if language == "zh"
            else "Budget guard blocks this run. Keep capital untouched."
        )
    elif action in {"WAIT", "HOLD"}:
        recommendation = "等待" if language == "zh" else "Wait"
        headline = (
            "当前信号不够干净，员工建议：继续观察，暂不下单。"
            if language == "zh"
            else "No clean small-trade edge yet. Wait for a stronger signal."
        )
    elif not is_live:
        recommendation = "仅测算法" if language == "zh" else "Algorithm Check Only"
        headline = (
            "你现在用的是手动/样例收盘价，这只能检查算法逻辑，不能代表当前市场。"
            if language == "zh"
            else "Manual/sample closes only check the algorithm; they do not represent the live market."
        )
    elif weak_backtest:
        recommendation = "暂不执行" if language == "zh" else "Do Not Execute Yet"
        headline = (
            f"实时方向偏 {micro_action_label(action, lang=language)}，但纸面回测不支持执行："
            f"胜率 {float(win_rate or 0):.0%}，盈亏 {total_pnl:+.5f}，{micro_halt_reason_label(halt_reason, lang=language)}。"
            if language == "zh"
            else (
                f"Live direction leans {action}, but the paper backtest does not support execution: "
                f"win rate {float(win_rate or 0):.0%}, P/L {total_pnl:+.5f}, {micro_halt_reason_label(halt_reason, lang=language)}."
            )
        )
    else:
        recommendation = "观察跟踪" if language == "zh" else "Watch"
        headline = (
            f"基于 {display_symbol} 最新K线，短线方向偏 {micro_action_label(action, lang=language)}；回测没有触发熔断，可加入观察清单。"
            if language == "zh"
            else f"Latest candles lean {action}; no circuit halt was triggered, so keep it on the watch list."
        )

    risk_items = (
        [
            f"单次金额：{decision.get('risk', {}).get('max_trade_amount', 'N/A')}",
            f"预算状态：{micro_budget_reason_label(budget_check.get('reason'), lang=language)}",
            f"熔断状态：{micro_halt_reason_label(halt_reason, lang=language)}",
        ]
        if language == "zh"
        else [
            f"Trade amount: {decision.get('risk', {}).get('max_trade_amount', 'N/A')}",
            f"Budget: {micro_budget_reason_label(budget_check.get('reason'), lang=language)}",
            f"Circuit breaker: {micro_halt_reason_label(halt_reason, lang=language)}",
        ]
    )
    if blockers:
        risk_items.append(
            ("阻断项：" if language == "zh" else "Blockers: ")
            + ", ".join(micro_blocker_label(item, lang=language) for item in blockers)
        )
    risk_items.append(
        ("数据来源：Deriv 最新K线" if is_live else "数据来源：手动/样例，不能代表实时市场")
        if language == "zh"
        else ("Data source: latest Deriv candles" if is_live else "Data source: manual/sample closes, not live market")
    )

    next_steps = []
    if not budget_ok:
        next_steps.append(
            "先降低单次金额，或确认已用预算后再尝试。"
            if language == "zh"
            else "Reduce amount or reset spent budget before any new attempt."
        )
    elif action in {"WAIT", "HOLD"}:
        next_steps.append(
            "先刷新/补充最新收盘价，再重新运行判断。"
            if language == "zh"
            else "Collect fresher closes and rerun before considering a trade."
        )
    elif not is_live:
        next_steps.append(
            "切换到 Deriv 最新K线，再跑一次；不要用样例数据做交易判断。"
            if language == "zh"
            else "Switch to latest Deriv candles and rerun before making any trading decision."
        )
    elif weak_backtest:
        next_steps.append(
            "不要下单；等下一根或下一组K线出来后重跑，必须看到胜率、盈亏、熔断同时改善。"
            if language == "zh"
            else "Do not trade; rerun after the next candles and require win rate, PnL, and circuit status to improve together."
        )
    else:
        next_steps.append(
            "把这次方向放入观察清单；连续多轮一致时，再去主交易台生成待确认订单。"
            if language == "zh"
            else "Track this direction; only draft a confirmed trade after repeated consistent runs."
        )
    next_steps.append(
        "不要绕过主交易台的人工确认闸门。"
        if language == "zh"
        else "Do not bypass the main trading desk confirmation gate."
    )

    return {
        "headline": headline,
        "recommendation": recommendation,
        "data_quality": "实时K线" if is_live and language == "zh" else "Live candles" if is_live else "样例/手动" if language == "zh" else "Manual/sample",
        "action": action,
        "action_label": micro_action_label(action, lang=language),
        "confidence": confidence,
        "latest_price": decision.get("latest_price"),
        "bars": len(frame),
        "trade_count": trade_count,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "ending_equity": summary.get("ending_equity"),
        "risk_items": risk_items,
        "evidence": {
            "momentum_3_pct": decision.get("momentum_3_pct"),
            "momentum_7_pct": decision.get("momentum_7_pct"),
            "volatility_pct": decision.get("volatility_pct"),
            "gross_edge_pct": decision.get("gross_edge_pct"),
            "short_ema": decision.get("short_ema"),
            "long_ema": decision.get("long_ema"),
        },
        "next_steps": next_steps,
    }


def micro_trades_table(trades: list[dict[str, Any]], *, lang: str | None = None) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    language = lang or current_lang()
    frame = pd.DataFrame(trades)
    if "action" in frame.columns:
        frame["action"] = frame["action"].apply(lambda value: micro_action_label(value, lang=language))
    frame["verdict"] = frame.apply(
        lambda row: (
            "通过"
            if language == "zh" and not row.get("blockers")
            else "Pass"
            if not row.get("blockers")
            else "阻断: " + ", ".join(micro_blocker_label(item, lang=language) for item in (row.get("blockers") or []))
            if language == "zh"
            else "Blocked: " + ", ".join(micro_blocker_label(item, lang=language) for item in (row.get("blockers") or []))
        ),
        axis=1,
    )
    columns = [
        "index",
        "action",
        "entry_price",
        "exit_price",
        "return_pct",
        "pnl",
        "equity",
        "confidence",
        "verdict",
    ]
    frame = frame[[column for column in columns if column in frame.columns]].copy()
    for column in ("entry_price", "exit_price", "return_pct", "pnl", "equity", "confidence"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").round(5)
    labels = (
        {
            "index": "K线序号",
            "action": "方向",
            "entry_price": "入场价",
            "exit_price": "出场价",
            "return_pct": "收益率%",
            "pnl": "盈亏",
            "equity": "权益",
            "confidence": "置信度",
            "verdict": "结果",
        }
        if language == "zh"
        else {
            "index": "Bar",
            "action": "Direction",
            "entry_price": "Entry",
            "exit_price": "Exit",
            "return_pct": "Return %",
            "pnl": "P/L",
            "equity": "Equity",
            "confidence": "Confidence",
            "verdict": "Result",
        }
    )
    return frame.rename(columns=labels)


def micro_run_record_view(record: dict[str, Any], *, lang: str | None = None) -> dict[str, Any]:
    language = lang or current_lang()
    payload = record.get("payload") or {}
    brief = payload.get("operator_brief") or {}
    backtest = payload.get("backtest") or {}
    summary = backtest.get("summary") or {}
    data_source = payload.get("data_source") or "unknown"
    win_rate = summary.get("win_rate")
    headline = brief.get("headline") or (
        "旧记录缺少员工结论，请重新运行。"
        if language == "zh"
        else "Legacy run without operator brief; rerun it."
    )
    return {
        ("时间" if language == "zh" else "Time"): local_time_label(record.get("created_at"), "%m-%d %H:%M MYT"),
        ("资产" if language == "zh" else "Symbol"): record.get("symbol"),
        ("数据" if language == "zh" else "Data"): (
            "实时K线"
            if data_source == "live" and language == "zh"
            else "Live candles"
            if data_source == "live"
            else "手动/样例"
            if language == "zh"
            else "Manual/sample"
        ),
        ("建议" if language == "zh" else "Recommendation"): brief.get("recommendation")
        or ("旧记录" if language == "zh" else "Legacy"),
        ("方向" if language == "zh" else "Direction"): brief.get("action_label")
        or micro_action_label(brief.get("action") or record.get("action"), lang=language),
        ("胜率" if language == "zh" else "Win Rate"): "N/A" if win_rate is None else f"{float(win_rate):.0%}",
        ("盈亏" if language == "zh" else "P/L"): f"{float(summary.get('total_pnl') if summary else record.get('total_pnl') or 0):+.5f}",
        ("熔断" if language == "zh" else "Halt"): micro_halt_reason_label(summary.get("halt_reason"), lang=language),
        ("结论" if language == "zh" else "Brief"): headline,
    }


def micro_recent_runs_table(rows: list[dict[str, Any]], *, lang: str | None = None) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([micro_run_record_view(row, lang=lang) for row in rows])


def render_micro_strategy_page() -> None:
    st.markdown(f"### {t('micro_strategy')}")
    st.markdown(f'<p class="small-muted">{html.escape(t("micro_strategy_caption"))}</p>', unsafe_allow_html=True)
    with st.container(border=True):
        top = st.columns([0.34, 0.22, 0.2, 0.24])
        goal = top[0].text_input(t("micro_goal"), value="高频小额交易，先做纸面策略")
        symbol = top[1].text_input(t("micro_symbol"), value="R_75")
        asset_kind = top[2].selectbox(t("micro_asset_kind"), ["deriv", "fund", "equity", "crypto", "forex"])
        trade_amount = top[3].number_input(t("micro_amount"), min_value=0.35, max_value=100.0, value=1.0, step=0.25)

        source_cols = st.columns([0.34, 0.22, 0.44])
        source_label = source_cols[0].selectbox(
            t("micro_data_source"),
            [t("micro_source_live"), t("micro_source_manual")],
        )
        live_count = source_cols[1].number_input(t("micro_live_count"), min_value=20, max_value=1000, value=120, step=20)
        live_granularity = source_cols[2].selectbox(
            t("micro_live_granularity"),
            [60, 120, 300, 900, 3600],
            format_func=lambda value: f"{int(value)}s",
        )
        data_source = "live" if source_label == t("micro_source_live") else "manual"
        if data_source == "manual":
            prices_text = st.text_area(t("micro_prices"), value=default_micro_prices(), height=104)
        else:
            prices_text = default_micro_prices()
            st.caption(
                "运行时会抓取 Deriv 最新K线；下面的手动价格不会参与本轮判断。"
                if current_lang() == "zh"
                else "The run will use latest Deriv candles; manual closes are ignored for this run."
            )
        budget_cols = st.columns(4)
        daily_budget = budget_cols[0].number_input(t("micro_daily_budget"), min_value=0.35, max_value=500.0, value=5.0, step=0.5)
        total_budget = budget_cols[1].number_input(t("micro_total_budget"), min_value=0.35, max_value=500.0, value=5.0, step=0.5)
        spent_today = budget_cols[2].number_input(t("micro_spent_today"), min_value=0.0, max_value=500.0, value=0.0, step=0.5)
        spent_total = budget_cols[3].number_input(t("micro_spent_total"), min_value=0.0, max_value=500.0, value=0.0, step=0.5)

        circuit_cols = st.columns(4)
        max_losses = circuit_cols[0].number_input(t("micro_max_losses"), min_value=1, max_value=10, value=3, step=1)
        max_loss_amount = circuit_cols[1].number_input(t("micro_max_loss_amount"), min_value=0.1, max_value=100.0, value=2.0, step=0.25)
        max_drawdown = circuit_cols[2].number_input(t("micro_max_drawdown"), min_value=0.1, max_value=50.0, value=3.0, step=0.25)
        max_trades = circuit_cols[3].number_input(t("micro_max_trades"), min_value=1, max_value=200, value=30, step=1)
        run_clicked = st.button(t("micro_run"), type="primary", width="stretch")

    if not run_clicked:
        recent_runs = load_recent_micro_strategy_runs()
        if recent_runs:
            st.markdown(f"#### {t('micro_recent_runs')}")
            recent_table = micro_recent_runs_table(recent_runs)
            st.dataframe(recent_table, width="stretch", height=min(340, 72 + len(recent_table) * 32))
        return

    config = MicroTradeConfig(
        symbol=normalize_deriv_symbol(symbol) if asset_kind == "deriv" else symbol.strip(),
        asset_kind=asset_kind,  # type: ignore[arg-type]
        max_trade_amount=float(trade_amount),
        min_confidence=0.58,
        max_volatility_pct=2.8 if asset_kind != "fund" else 2.2,
    )
    actual_data_source = data_source
    if data_source == "live" and asset_kind == "deriv":
        live_result = fetch_compare_candles(config.symbol, int(live_granularity), int(live_count))
        if not live_result.get("ok"):
            st.error(
                "实时K线抓取失败，本轮不会生成交易建议。"
                if current_lang() == "zh"
                else "Live candle fetch failed; no trading suggestion is produced."
            )
            st.json(live_result)
            return
        live_frame = candles_frame_from_result(live_result)
        frame = normalize_price_frame(live_frame[["timestamp", "close"]])
        push_runtime_event(
            "micro_strategy",
            "Deriv Candles",
            "Micro Strategy",
            f"{config.symbol} live candles loaded",
            {"symbol": config.symbol, "granularity": int(live_granularity), "count": len(frame)},
        )
    else:
        frame = micro_price_frame_from_text(prices_text)
        actual_data_source = "manual"
        if data_source == "live" and asset_kind != "deriv":
            st.warning(
                "非 Deriv 资产暂时没有实时行情接入，本轮按手动输入模式处理。"
                if current_lang() == "zh"
                else "Live data is not wired for non-Deriv assets yet; this run uses manual input."
            )
    budget_check = budget_guard_check(
        action="execute_simulated_trade" if asset_kind == "deriv" else "spot_paper_trade",
        amount=trade_amount,
        limits=BudgetLimits(
            max_single_trade_amount=float(trade_amount),
            max_daily_trade_budget=float(daily_budget),
            max_total_trade_budget=float(total_budget),
        ),
        daily_spent=float(spent_today),
        total_spent=float(spent_total),
    )
    decision = analyze_micro_trade(frame, config)
    if not budget_check.get("ok"):
        decision["action"] = "WAIT" if asset_kind == "deriv" else "HOLD"
        decision["blockers"] = list(decision.get("blockers") or []) + [str(budget_check.get("reason"))]

    backtest = backtest_micro_strategy(
        frame,
        config,
        CircuitBreakerConfig(
            max_consecutive_losses=int(max_losses),
            max_total_loss_amount=float(max_loss_amount),
            max_drawdown_pct=float(max_drawdown),
            max_trade_count=int(max_trades),
        ),
        lookback_bars=8,
    )
    operator_brief = micro_operator_brief(
        decision,
        budget_check,
        backtest,
        frame,
        data_source=actual_data_source,
        symbol=config.symbol,
    )
    save_micro_strategy_run(
        goal=goal,
        config=config,
        decision=decision,
        budget_check=budget_check,
        backtest=backtest,
        operator_brief=operator_brief,
        data_source=actual_data_source,
    )
    push_runtime_event(
        "micro_strategy",
        "Micro Strategy",
        "Sync Bus",
        f"{config.symbol} {operator_brief.get('recommendation')} run saved",
        {
            "symbol": config.symbol,
            "recommendation": operator_brief.get("recommendation"),
            "action": decision.get("action"),
            "budget_ok": budget_check.get("ok"),
            "trade_count": (backtest.get("summary") or {}).get("trade_count"),
        },
    )
    st.success(t("micro_saved"))

    st.markdown(f"#### {t('micro_operator_brief')}")
    st.info(operator_brief["headline"])
    brief_cols = st.columns(6)
    brief_cols[0].metric(t("micro_operator_recommendation"), operator_brief["recommendation"])
    brief_cols[1].metric(t("micro_trade_direction"), operator_brief["action_label"])
    brief_cols[2].metric("置信度" if current_lang() == "zh" else "Confidence", f"{operator_brief['confidence']:.0%}")
    brief_cols[3].metric(t("micro_paper_return"), f"{operator_brief['total_pnl']:+.5f}")
    brief_cols[4].metric("回测次数" if current_lang() == "zh" else "Trades", int(operator_brief["trade_count"]))
    brief_cols[5].metric(t("micro_data_quality"), operator_brief["data_quality"])

    info_cols = st.columns([0.34, 0.33, 0.33])
    with info_cols[0]:
        st.markdown(f"##### {t('micro_risk_brief')}")
        for item in operator_brief["risk_items"]:
            st.markdown(f"- `{item}`")
    with info_cols[1]:
        st.markdown(f"##### {t('micro_evidence')}")
        evidence_names = (
            {
                "momentum_3_pct": "最近3根动量%",
                "momentum_7_pct": "最近7根动量%",
                "volatility_pct": "波动率%",
                "gross_edge_pct": "扣成本后优势%",
                "short_ema": "短均线",
                "long_ema": "长均线",
            }
            if current_lang() == "zh"
            else {
                "momentum_3_pct": "3-bar Momentum %",
                "momentum_7_pct": "7-bar Momentum %",
                "volatility_pct": "Volatility %",
                "gross_edge_pct": "Cost-adjusted Edge %",
                "short_ema": "Short EMA",
                "long_ema": "Long EMA",
            }
        )
        evidence_rows = [
            {
                ("指标" if current_lang() == "zh" else "Signal"): evidence_names.get(key, key),
                ("数值" if current_lang() == "zh" else "Value"): value,
            }
            for key, value in operator_brief["evidence"].items()
        ]
        st.dataframe(evidence_rows, width="stretch", hide_index=True, height=248)
    with info_cols[2]:
        st.markdown(f"##### {t('micro_next_steps')}")
        for item in operator_brief["next_steps"]:
            st.markdown(f"- {html.escape(item)}")

    st.markdown(f"#### {t('micro_decision')}")
    cols = st.columns(5)
    cols[0].metric("方向" if current_lang() == "zh" else "Direction", micro_action_label(decision.get("action")))
    cols[1].metric("置信度" if current_lang() == "zh" else "Confidence", f"{float(decision.get('confidence') or 0):.0%}")
    cols[2].metric("波动率" if current_lang() == "zh" else "Volatility", f"{float(decision.get('volatility_pct') or 0):.3f}%")
    cols[3].metric("预算" if current_lang() == "zh" else "Budget", micro_budget_reason_label(budget_check.get("reason")))
    cols[4].metric("数据条数" if current_lang() == "zh" else "Bars", len(frame))
    with st.expander("原始数据（排错用）" if current_lang() == "zh" else "Raw Data For Debugging", expanded=False):
        st.json({"decision": decision, "budget_guard": budget_check})

    st.markdown(f"#### {t('micro_backtest')}")
    summary = backtest.get("summary") or {}
    backtest_cols = st.columns(5)
    backtest_cols[0].metric("回测次数" if current_lang() == "zh" else "Trades", int(summary.get("trade_count") or 0))
    backtest_cols[1].metric("胜率" if current_lang() == "zh" else "Win Rate", "N/A" if summary.get("win_rate") is None else f"{float(summary['win_rate']):.0%}")
    backtest_cols[2].metric("盈亏" if current_lang() == "zh" else "P/L", f"{float(summary.get('total_pnl') or 0):+.5f}")
    backtest_cols[3].metric("权益" if current_lang() == "zh" else "Equity", f"{float(summary.get('ending_equity') or 100):.5f}")
    backtest_cols[4].metric("熔断" if current_lang() == "zh" else "Halt", micro_halt_reason_label(summary.get("halt_reason")))
    trades = backtest.get("trades") or []
    trade_table = micro_trades_table(trades)
    if not trade_table.empty:
        st.markdown(f"##### {t('micro_trade_log')}")
        st.dataframe(trade_table, width="stretch", height=min(360, 72 + len(trade_table) * 32))
    else:
        st.info(t("micro_no_trade"))

    recent_runs = load_recent_micro_strategy_runs()
    if recent_runs:
        st.markdown(f"#### {t('micro_recent_runs')}")
        recent_table = micro_recent_runs_table(recent_runs)
        st.dataframe(recent_table, width="stretch", height=min(340, 72 + len(recent_table) * 32))


def render_trading_page() -> None:
    render_safety_gate_panel()
    render_pending_trade_panel(show_raw=False)
    render_chat()


def render_charts_page() -> None:
    st.markdown(f"### {t('live_results')}")
    st.markdown(f'<p class="small-muted">{html.escape(t("results_hint"))}</p>', unsafe_allow_html=True)
    render_chart_loader_controls()
    render_last_artifacts()


def render_monitor_page() -> None:
    render_system_health_panel()
    render_swarm_graph()
    render_agent_roster()
    render_sync_bus()
    render_audit_export_panel()


def main() -> None:
    init_state()
    configure_page()
    render_sidebar()
    render_header()
    render_global_status_bar()
    active_page = render_page_nav()
    if active_page == "advisor":
        render_advisor_page()
    elif active_page == "micro":
        render_micro_strategy_page()
    elif active_page == "trading":
        render_trading_page()
    elif active_page == "charts":
        render_charts_page()
    else:
        render_monitor_page()


if __name__ == "__main__":
    main()
