"""Modern FastAPI entrypoint for the multi-broker AI trading gateway."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import logging
import os

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from pydantic import BaseModel, Field
import pandas as pd
import httpx

from agent_streaming import (
    ChatRuntimeConfig,
    create_chat_session,
    ensure_chat_session,
    finish_agent_run,
    init_chat_db,
    list_agent_runs,
    list_chat_sessions,
    load_chat_messages,
    load_prompt_registry,
    market_context,
    recover_interrupted_runs,
    save_chat_message,
    start_agent_run,
    stream_multi_agent_chat,
)
from broker_hub import (
    broker_catalog,
    delete_broker_profile,
    get_broker,
    init_broker_db,
    list_broker_profiles,
    public_market_snapshot,
    save_broker_profile,
    test_broker_connection,
)
from case_evidence import persist_chat_case_evidence
from case_workflow import trade_case_decision_snapshot
from micro_trading import MicroTradeConfig, analyze_micro_trade, normalize_price_frame
from paper_trading import CircuitBreakerConfig, backtest_micro_strategy
from risk_policy import evaluate_global_risk, get_risk_policy, init_risk_policy_db, update_risk_policy
from trade_cases import (
    TradeCaseConflict,
    TradeCaseTransitionError,
    create_trade_case,
    get_trade_case,
    init_trade_case_db,
    list_trade_case_events,
    list_trade_cases,
    record_trade_case_artifact,
)


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "local_data"
DB_PATH = DATA_DIR / "gateway.sqlite3"
PROMPTS_PATH = ROOT / "agent_prompts.json"
FRONTEND_DIST = ROOT / "frontend" / "dist"

# Configure structured logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gateway")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12_000)
    session_id: str | None = None
    case_id: str | None = None
    provider: str = "local"
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    language: str = "zh"
    broker_id: str = Field(default="deriv", min_length=2, max_length=32)


class SessionRequest(BaseModel):
    title: str = "New conversation"


class StrategyRequest(BaseModel):
    symbol: str = "R_75"
    amount: float = Field(default=1.0, gt=0, le=10)
    broker_id: str = Field(default="deriv", min_length=2, max_length=32)


class TradeCaseRequest(BaseModel):
    objective: str = Field(min_length=3, max_length=2_000)
    symbol: str = Field(default="R_75", min_length=2, max_length=32)
    title: str = Field(default="", max_length=120)
    broker_id: str = Field(default="deriv", min_length=2, max_length=32)


class BrokerProfileRequest(BaseModel):
    profile_id: str | None = None
    broker_id: str = Field(min_length=2, max_length=32)
    label: str = Field(default="", max_length=80)
    environment: str = Field(min_length=2, max_length=32)
    account_id: str = Field(default="", max_length=160)
    is_default: bool = False
    settings: dict[str, Any] = Field(default_factory=dict)


class BrokerConnectionTestRequest(BaseModel):
    environment: str = Field(min_length=2, max_length=32)
    account_id: str = Field(default="", max_length=160)
    credentials: dict[str, str] = Field(default_factory=dict)


class RiskPolicyRequest(BaseModel):
    enabled: bool = True
    max_single_trade_amount: float = Field(gt=0, le=1_000)
    max_daily_trade_budget: float = Field(gt=0, le=10_000)
    max_total_trade_budget: float = Field(gt=0, le=1_000_000)
    max_daily_loss: float = Field(gt=0, le=10_000)
    max_open_positions: int = Field(gt=0, le=100)
    cooldown_seconds: int = Field(ge=0, le=86_400)


class DecisionActionRequest(BaseModel):
    action: str
    note: str = Field(default="", max_length=1_000)
    expected_version: int = Field(gt=0)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_chat_db(DB_PATH)
    recover_interrupted_runs(DB_PATH)
    init_trade_case_db(DB_PATH)
    init_risk_policy_db(DB_PATH)
    init_broker_db(DB_PATH)
    yield


app = FastAPI(title="Multi-Broker AI Trading Gateway API", version="3.0.0", lifespan=lifespan)
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, lambda request, exc: HTTPException(status_code=429, detail="Rate limit exceeded. Please slow down."))

# CORS origins from env (comma-separated) or sensible dev defaults
_cors_env = os.getenv("CORS_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in _cors_env.split(",") if o.strip()] or [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        database = str(DB_PATH.relative_to(ROOT))
    except ValueError:
        database = str(DB_PATH)
    return {
        "ok": True,
        "runtime": "fastapi",
        "streaming": "sse",
        "database": database,
        "frontend_built": FRONTEND_DIST.exists(),
    }


@app.get("/api/agents")
def agents() -> dict[str, Any]:
    registry = load_prompt_registry(PROMPTS_PATH)
    return {
        "agents": [
            {"id": key, "name": value.get("name"), "prompt": value.get("prompt")}
            for key, value in registry.items()
            if not key.startswith("advisor.")
        ]
    }


@app.get("/api/market/{symbol}")
async def market(symbol: str, broker_id: str = "deriv") -> dict[str, Any]:
    try:
        get_broker(broker_id)
        data = (
            await market_context(symbol.strip().upper())
            if broker_id == "deriv"
            else await public_market_snapshot(broker_id, symbol)
        )
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    data["broker_id"] = broker_id
    return {"market": data}


@app.post("/api/strategy/analyze")
@limiter.limit("10/minute")
async def strategy(request: StrategyRequest, request_obj: Request) -> dict[str, Any]:
    try:
        get_broker(request.broker_id)
        market = (
            await market_context(request.symbol.strip().upper())
            if request.broker_id == "deriv"
            else await public_market_snapshot(request.broker_id, request.symbol)
        )
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    closes = market.get("closes") or []
    if len(closes) < 20:
        raise HTTPException(status_code=422, detail="not enough candle data for strategy analysis")
    frame = normalize_price_frame(pd.DataFrame({"close": closes}))
    config = MicroTradeConfig(symbol=request.symbol.strip().upper(), max_trade_amount=request.amount)
    decision = analyze_micro_trade(frame, config)
    budget = evaluate_global_risk(
        DB_PATH,
        action="execute_simulated_trade",
        amount=request.amount,
    )
    backtest = backtest_micro_strategy(frame, config, CircuitBreakerConfig(), lookback_bars=8)
    backtest_summary = backtest.get("summary") or {}
    safety_blockers = list(decision.get("blockers") or [])
    if not budget.get("ok"):
        safety_blockers.extend(budget.get("blockers") or ["budget_blocked"])
    if backtest_summary.get("halted") and backtest_summary.get("halt_reason") != "max_trade_count":
        safety_blockers.append("circuit_breaker_halted")
    if safety_blockers:
        decision = {**decision, "action": "WAIT", "blockers": list(dict.fromkeys(safety_blockers))}
    if request.broker_id != "deriv":
        action_map = {"CALL": "BUY", "PUT": "SELL", "WAIT": "HOLD"}
        decision = {**decision, "action": action_map.get(str(decision.get("action")), "HOLD")}
    return {
        "symbol": config.symbol,
        "broker_id": request.broker_id,
        "amount": request.amount,
        "market": {key: value for key, value in market.items() if key != "closes"},
        "decision": decision,
        "budget": budget,
        "backtest": backtest,
    }


@app.post("/api/chat/session")
def chat_session(request: SessionRequest) -> dict[str, str]:
    session_id = create_chat_session(DB_PATH, request.title)
    return {"session_id": session_id, "title": request.title}


@app.get("/api/chat/sessions")
def chat_sessions() -> dict[str, Any]:
    return {"sessions": list_chat_sessions(DB_PATH, limit=40)}


@app.get("/api/runs")
def agent_runs() -> dict[str, Any]:
    return {"runs": list_agent_runs(DB_PATH, limit=30)}


@app.get("/api/chat/history/{session_id}")
def chat_history(session_id: str) -> dict[str, Any]:
    resolved = ensure_chat_session(DB_PATH, session_id)
    return {"session_id": resolved, "messages": load_chat_messages(DB_PATH, resolved, 80)}


@app.post("/api/chat/stream")
@limiter.limit("30/minute")
async def chat_stream(request: ChatRequest, request_obj: Request) -> StreamingResponse:
    provider = request.provider.strip().lower()
    if provider not in {"local", "openai", "deepseek", "anthropic", "compatible"}:
        raise HTTPException(status_code=400, detail="unsupported provider")
    if provider != "local" and not request.api_key.strip():
        raise HTTPException(status_code=400, detail="api_key is required for the selected provider")
    if provider == "compatible" and not request.base_url.strip():
        raise HTTPException(status_code=400, detail="base_url is required for compatible providers")

    linked_case = None
    if request.case_id:
        linked_case = get_trade_case(DB_PATH, request.case_id.strip())
        if linked_case is None:
            raise HTTPException(status_code=404, detail="trade case not found")
        if linked_case["status"] != "active":
            raise HTTPException(
                status_code=409,
                detail=f"trade case is {linked_case['status']}; resume it before running agents",
            )

    selected_broker_id = str(linked_case.get("broker_id") or "deriv") if linked_case else request.broker_id.strip().lower()
    try:
        get_broker(selected_broker_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    async def selected_market_loader(symbol: str) -> dict[str, Any]:
        result = (
            await market_context(symbol)
            if selected_broker_id == "deriv"
            else await public_market_snapshot(selected_broker_id, symbol)
        )
        return {**result, "broker_id": selected_broker_id}

    session_id = ensure_chat_session(DB_PATH, request.session_id)
    history = load_chat_messages(DB_PATH, session_id, 30)
    save_chat_message(DB_PATH, session_id, "user", request.message)
    config = ChatRuntimeConfig(
        provider=provider,
        api_key=request.api_key.strip(),
        model=request.model.strip(),
        base_url=request.base_url.strip(),
        language="en" if request.language == "en" else "zh",
    )

    async def events():
        stream_started_at = datetime.now(timezone.utc)
        answer = ""
        metadata: dict[str, Any] = {}
        market_snapshot: dict[str, Any] | None = None
        agent_reports: dict[str, dict[str, str]] = {}
        routed_agents: list[str] = []
        run_id = ""
        run_spans: list[dict[str, Any]] = []
        try:
            yield _sse({"type": "session", "session_id": session_id})
            if linked_case is not None:
                running_case = _record_case_artifact(
                    linked_case["id"],
                    artifact_type="workflow_run",
                    actor="manager",
                    message="经理已派发本轮多 Agent 分析",
                    payload={
                        "status": "running",
                        "current_step": "manager_dispatch",
                        "completed_steps": [],
                        "session_id": session_id,
                        "question": request.message,
                        "broker_id": selected_broker_id,
                    },
                )
                yield _sse(_case_updated_event(running_case))
            async for event in stream_multi_agent_chat(
                message=request.message,
                history=history,
                config=config,
                prompts_path=PROMPTS_PATH,
                symbol_override=str(linked_case["symbol"]) if linked_case else None,
                market_loader=selected_market_loader,
            ):
                event_type = event.get("type")
                if event_type == "start":
                    run_id = str(event.get("run_id") or "")
                    routed_agents = list(event.get("route") or [])
                    if run_id:
                        start_agent_run(
                            DB_PATH,
                            run_id=run_id,
                            session_id=session_id,
                            case_id=str(linked_case["id"]) if linked_case else None,
                            provider=provider,
                            model=config.resolved_model,
                            symbol=str(event.get("symbol") or ""),
                            route=routed_agents,
                        )
                elif event_type in {"agent_done", "agent_error"}:
                    agent_id = str(event.get("agent_id") or event.get("name") or "agent")
                    agent_reports[agent_id] = {
                        "name": str(event.get("name") or agent_id),
                        "report": str(event.get("report") or ""),
                    }
                    run_spans.append(
                        {
                            "agent_id": agent_id,
                            "name": str(event.get("name") or agent_id),
                            "status": "completed" if event_type == "agent_done" else "failed",
                            "duration_ms": int(event.get("duration_ms") or 0),
                            "error_code": event.get("error_code"),
                        }
                    )
                elif event_type == "tool_done" and event.get("tool") == "market_snapshot":
                    data = event.get("data")
                    market_snapshot = data if isinstance(data, dict) else None
                elif event_type == "answer_delta":
                    answer += str(event.get("delta") or "")
                elif event_type == "done":
                    answer = str(event.get("answer") or answer)
                    metadata = {
                        "symbol": event.get("symbol"),
                        "reports": event.get("reports") or {},
                        "provider": provider,
                        "model": config.resolved_model,
                        "case_id": linked_case["id"] if linked_case else None,
                        "broker_id": selected_broker_id,
                        "run_id": run_id,
                        "elapsed_ms": event.get("elapsed_ms"),
                        "successful_agents": event.get("successful_agents") or [],
                        "failed_agents": event.get("failed_agents") or [],
                        "manager_fallback": bool(event.get("manager_fallback")),
                    }
                    if run_id:
                        degraded = bool(event.get("failed_agents")) or bool(event.get("manager_fallback"))
                        finish_agent_run(
                            DB_PATH,
                            run_id,
                            status="degraded" if degraded else "completed",
                            spans=run_spans,
                            elapsed_ms=int(event.get("elapsed_ms") or 0),
                        )
                    if linked_case is not None:
                        for case_event in persist_chat_case_evidence(
                            linked_case,
                            question=request.message,
                            answer=answer,
                            reports=agent_reports,
                            market=market_snapshot,
                            route=routed_agents,
                            session_id=session_id,
                            provider=provider,
                            model=config.resolved_model,
                        ):
                            yield _sse(case_event)
                yield _sse(event)
        except asyncio.CancelledError:
            metadata = {
                **metadata,
                "run_id": run_id,
                "status": "cancelled",
                "provider": provider,
                "model": config.resolved_model,
            }
            if run_id:
                finish_agent_run(
                    DB_PATH,
                    run_id,
                    status="cancelled",
                    spans=run_spans,
                    elapsed_ms=int(
                        (datetime.now(timezone.utc) - stream_started_at).total_seconds() * 1000
                    ),
                    error="client_disconnected",
                )
            raise
        except Exception as exc:
            logger.exception("chat_stream failed for session %s", session_id)
            if run_id:
                finish_agent_run(
                    DB_PATH,
                    run_id,
                    status="failed",
                    spans=run_spans,
                    elapsed_ms=int(
                        (datetime.now(timezone.utc) - stream_started_at).total_seconds() * 1000
                    ),
                    error=type(exc).__name__,
                )
            if linked_case is not None:
                try:
                    failed_case = _record_case_artifact(
                        linked_case["id"],
                        artifact_type="workflow_run",
                        actor="manager",
                        message="本轮多 Agent 分析失败",
                        payload={
                            "status": "failed",
                            "current_step": "manager_dispatch",
                            "failed_step": "manager_dispatch",
                            "completed_steps": [],
                            "session_id": session_id,
                            "error": type(exc).__name__,
                        },
                    )
                    yield _sse(_case_updated_event(failed_case))
                except (KeyError, TradeCaseTransitionError):
                    pass
            yield _sse({"type": "error", "message": "运行失败，请检查模型配置或稍后重试。"})
        finally:
            if answer.strip():
                save_chat_message(DB_PATH, session_id, "assistant", answer, metadata)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _case_summary(case: dict[str, Any]) -> dict[str, Any]:
    # NOTE: Case evidence logic has been extracted to case_evidence.py
    # This local helper is retained only for the /api/decisions endpoint.
    return {
        "id": case["id"],
        "title": case["title"],
        "objective": case["objective"],
        "symbol": case["symbol"],
        "broker_id": case.get("broker_id", "deriv"),
        "status": case["status"],
        "stage": case["stage"],
        "version": case["version"],
        "updated_at": case["updated_at"],
    }


def _case_updated_event(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "case_updated",
        "case": _case_summary(case),
        "decision": trade_case_decision_snapshot(case),
    }


def _decision_inbox_item(case: dict[str, Any]) -> dict[str, Any]:
    snapshot = trade_case_decision_snapshot(case)
    pending = snapshot["pending"]
    if pending["exists"]:
        global_risk = evaluate_global_risk(
            DB_PATH,
            action="execute_simulated_trade",
            amount=pending["amount"],
        )
    else:
        global_risk = {
            "ok": False,
            "blockers": ["missing_trade_draft"],
            "budget": {"ok": False, "reason": "missing_trade_draft"},
        }
    operator_decision = snapshot.get("operator_decision") or {}
    previous = str(operator_decision.get("decision") or "")
    decision_is_current = operator_decision.get("version") == case.get("version")
    if decision_is_current and previous in {"approved", "rejected", "evidence_requested"}:
        state = previous
    elif snapshot["gate"]["ok"] and pending["exists"] and global_risk["ok"]:
        state = "ready"
    else:
        state = "blocked"
    evidence_points = sum(
        (
            20 if snapshot["advisor"]["action"] else 0,
            20 if snapshot["market"]["latest_close"] is not None else 0,
            25 if snapshot["strategy"]["action"] else 0,
            20 if snapshot["gate"]["ok"] is not None else 0,
            15 if pending["exists"] else 0,
        )
    )
    blockers = list(dict.fromkeys([*snapshot["gate"]["blockers"], *global_risk.get("blockers", [])]))
    return {
        "case": _case_summary(case),
        "decision": snapshot,
        "state": state,
        "evidence_score": evidence_points,
        "blockers": blockers,
        "global_risk": global_risk,
    }


def _record_case_artifact(
    case_id: str,
    *,
    artifact_type: str,
    actor: str,
    message: str,
    payload: dict[str, Any],
    advance_stage: bool = True,
    target_stage: str | None = None,
) -> dict[str, Any]:
    return record_trade_case_artifact(
        DB_PATH,
        case_id,
        artifact_type=artifact_type,
        actor=actor,
        message=message,
        payload=payload,
        advance_stage=advance_stage,
        target_stage=target_stage,
    )


def _direction_from_answer(answer: str, broker_id: str = "deriv") -> str:
    # Moved to case_evidence.py — retained here for backward compat with legacy callers.
    normalized = answer.upper()
    positive = "CALL" in normalized or "BUY" in normalized or "看涨" in answer or "买入" in answer
    negative = "PUT" in normalized or "SELL" in normalized or "看跌" in answer or "卖出" in answer
    if positive == negative:
        return "WAIT" if broker_id == "deriv" else "HOLD"
    if broker_id == "deriv":
        return "CALL" if positive else "PUT"
    return "BUY" if positive else "SELL"


def _market_artifact(market: dict[str, Any], symbol: str) -> dict[str, Any]:
    candle_count = int(market.get("candle_count") or 0)
    feed_ok = bool(market.get("ok"))
    issues: list[str] = []
    if not feed_ok:
        issues.append("market_feed_unavailable")
    if candle_count < 20:
        issues.append("insufficient_candles")
    tick = market.get("tick") if isinstance(market.get("tick"), dict) else {}
    epoch = tick.get("epoch") if tick else None
    latest_timestamp = None
    if isinstance(epoch, (int, float)):
        latest_timestamp = datetime.fromtimestamp(epoch, timezone.utc).isoformat()
    return {
        "broker_id": market.get("broker_id", "deriv"),
        "symbol": symbol,
        "latest_close": market.get("latest_close") or (tick or {}).get("quote"),
        "latest_timestamp": latest_timestamp,
        "candle_count": candle_count,
        "window_change_pct": market.get("window_change_pct"),
        "integrity": {
            "ok": feed_ok and candle_count >= 20,
            "fresh": feed_ok,
            "issues": issues,
        },
    }


# ---------------------------------------------------------------------------
# DEPRECATED: _persist_chat_case_evidence and helpers below have been moved to
# case_evidence.py (persist_chat_case_evidence). Retained temporarily for
# reference; safe to delete once migration is verified.
# ---------------------------------------------------------------------------
def _persist_chat_case_evidence(
    linked_case: dict[str, Any],
    *,
    question: str,
    answer: str,
    reports: dict[str, dict[str, str]],
    market: dict[str, Any] | None,
    route: list[str],
    session_id: str,
    provider: str,
    model: str,
) -> list[dict[str, Any]]:
    case_id = str(linked_case["id"])
    symbol = str(linked_case["symbol"])
    broker_id = str(linked_case.get("broker_id") or "deriv")
    stance = _direction_from_answer(answer, broker_id)
    updated: list[dict[str, Any]] = []
    advisor_case = _record_case_artifact(
        case_id,
        artifact_type="advisor",
        actor="advisor_council",
        message="谋士团结论已从经理对话同步",
        payload={
            "question": question,
            "symbol": symbol,
            "broker_id": broker_id,
            "stance": stance,
            "confidence": 0.68 if stance in {"CALL", "PUT", "BUY", "SELL"} else 0.45,
            "consensus": answer,
            "reports": reports,
            "route": route,
            "session_id": session_id,
            "provider": provider,
            "model": model,
        },
    )
    updated.append(_case_updated_event(advisor_case))

    completed_steps = ["manager_dispatch", "advisor_review"]
    if market is not None:
        market_case = _record_case_artifact(
            case_id,
            artifact_type="market",
            actor="market_agent",
            message="行情快照已同步到交易任务",
            payload=_market_artifact(market, symbol),
        )
        updated.append(_case_updated_event(market_case))
        completed_steps.append("market_validation")

    blockers = ["analysis_only", "micro_strategy_not_run", "human_confirmation_required"]
    if market is None:
        blockers.append("market_snapshot_not_run")
    risk_case = _record_case_artifact(
        case_id,
        artifact_type="risk",
        actor="risk_agent",
        message="风控 Agent 已记录剩余前置条件",
        payload={
            "ok": False,
            "blockers": blockers,
            "warnings": ["No order draft was created from chat"],
            "symbol": symbol,
            "broker_id": broker_id,
            "session_id": session_id,
        },
        advance_stage=False,
    )
    updated.append(_case_updated_event(risk_case))

    workflow_case = _record_case_artifact(
        case_id,
        artifact_type="workflow_run",
        actor="manager",
        message="本轮分析完成，下一步进入小笔策略纸面回测",
        payload={
            "status": "analysis_complete",
            "current_step": "micro_backtest",
            "completed_steps": completed_steps,
            "session_id": session_id,
            "broker_id": broker_id,
            "detail": {"blockers": blockers, "warnings": []},
        },
        target_stage="micro_backtest",
    )
    updated.append(_case_updated_event(workflow_case))
    return updated


@app.get("/api/risk-policy")
def risk_policy() -> dict[str, Any]:
    return get_risk_policy(DB_PATH)


@app.put("/api/risk-policy")
def save_risk_policy(request: RiskPolicyRequest) -> dict[str, Any]:
    try:
        return update_risk_policy(DB_PATH, request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/decisions")
def decision_inbox() -> dict[str, Any]:
    items = [
        _decision_inbox_item(case)
        for case in list_trade_cases(DB_PATH, limit=50)
        if case["status"] not in {"cancelled", "completed"}
    ]
    order = {"ready": 0, "evidence_requested": 1, "blocked": 2, "approved": 3, "rejected": 4}
    items.sort(key=lambda item: (order.get(item["state"], 9), -int(item["case"]["version"])))
    return {
        "items": items,
        "counts": {
            state: sum(item["state"] == state for item in items)
            for state in ("ready", "blocked", "evidence_requested", "approved", "rejected")
        },
        "risk_policy": get_risk_policy(DB_PATH),
    }


@app.post("/api/decisions/{case_id}/action")
def decide_case(case_id: str, request: DecisionActionRequest) -> dict[str, Any]:
    action = request.action.strip().lower()
    if action not in {"approve", "reject", "request_evidence"}:
        raise HTTPException(status_code=422, detail="unknown decision action")
    case = get_trade_case(DB_PATH, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="trade case not found")
    item = _decision_inbox_item(case)
    if action == "approve" and item["state"] != "ready":
        raise HTTPException(
            status_code=409,
            detail={"message": "decision is not ready for approval", "blockers": item["blockers"]},
        )
    decision = {"approve": "approved", "reject": "rejected", "request_evidence": "evidence_requested"}[action]
    payload = {
        "decision": decision,
        "note": request.note.strip(),
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "global_risk": item["global_risk"],
    }
    try:
        updated = record_trade_case_artifact(
            DB_PATH,
            case_id,
            artifact_type="operator_decision",
            actor="operator",
            message=f"Operator decision: {decision}",
            payload=payload,
            expected_version=request.expected_version,
        )
    except TradeCaseConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TradeCaseTransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"item": _decision_inbox_item(updated)}


@app.get("/api/brokers")
def brokers() -> dict[str, Any]:
    return {"brokers": broker_catalog(), "profiles": list_broker_profiles(DB_PATH)}


@app.put("/api/broker-profiles")
def upsert_broker_profile(request: BrokerProfileRequest) -> dict[str, Any]:
    try:
        profile = save_broker_profile(
            DB_PATH,
            broker_id=request.broker_id,
            label=request.label,
            environment=request.environment,
            account_id=request.account_id,
            is_default=request.is_default,
            settings=request.settings,
            profile_id=request.profile_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"profile": profile, "profiles": list_broker_profiles(DB_PATH)}


@app.delete("/api/broker-profiles/{profile_id}")
def remove_broker_profile(profile_id: str) -> dict[str, Any]:
    if not delete_broker_profile(DB_PATH, profile_id):
        raise HTTPException(status_code=404, detail="broker profile not found")
    return {"ok": True, "profiles": list_broker_profiles(DB_PATH)}


@app.post("/api/brokers/{broker_id}/test")
@limiter.limit("10/minute")
async def broker_connection_test(broker_id: str, request: BrokerConnectionTestRequest, request_obj: Request) -> dict[str, Any]:
    try:
        get_broker(broker_id)
        return await test_broker_connection(
            broker_id=broker_id,
            environment=request.environment,
            account_id=request.account_id,
            credentials=request.credentials,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/cases")
def cases() -> dict[str, Any]:
    rows = list_trade_cases(DB_PATH, limit=30)
    return {
        "cases": [
            {
                "id": row["id"],
                "title": row["title"],
                "objective": row["objective"],
                "symbol": row["symbol"],
                "broker_id": row.get("broker_id", "deriv"),
                "status": row["status"],
                "stage": row["stage"],
                "version": row["version"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    }


@app.post("/api/cases", status_code=201)
@limiter.limit("20/minute")
def create_case(request: TradeCaseRequest, request_obj: Request) -> dict[str, Any]:
    try:
        get_broker(request.broker_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    case = create_trade_case(
        DB_PATH,
        objective=request.objective,
        symbol=request.symbol.strip().upper(),
        title=request.title,
        broker_id=request.broker_id,
    )
    return {"case": case, "decision": trade_case_decision_snapshot(case)}


@app.get("/api/cases/{case_id}")
def case_detail(case_id: str) -> dict[str, Any]:
    case = get_trade_case(DB_PATH, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="trade case not found")
    return {
        "case": case,
        "decision": trade_case_decision_snapshot(case),
        "events": list_trade_case_events(DB_PATH, case_id, limit=100),
    }


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


if FRONTEND_DIST.exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}")
    def frontend(path: str) -> FileResponse:
        root = FRONTEND_DIST.resolve()
        target = (FRONTEND_DIST / path).resolve()
        if path and target.is_relative_to(root) and target.is_file():
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("gateway_api:app", host="127.0.0.1", port=8765, reload=False)
