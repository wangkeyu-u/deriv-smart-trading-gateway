"""Modern FastAPI entrypoint for the Deriv Smart Trading Gateway UI."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import pandas as pd

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
from case_workflow import trade_case_decision_snapshot
from budget_guard import BudgetLimits, budget_guard_check
from micro_trading import MicroTradeConfig, analyze_micro_trade, normalize_price_frame
from paper_trading import CircuitBreakerConfig, backtest_micro_strategy
from trade_cases import (
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


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12_000)
    session_id: str | None = None
    case_id: str | None = None
    provider: str = "local"
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    language: str = "zh"


class SessionRequest(BaseModel):
    title: str = "New conversation"


class StrategyRequest(BaseModel):
    symbol: str = "R_75"
    amount: float = Field(default=1.0, gt=0, le=10)


class TradeCaseRequest(BaseModel):
    objective: str = Field(min_length=3, max_length=2_000)
    symbol: str = Field(default="R_75", min_length=2, max_length=32)
    title: str = Field(default="", max_length=120)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_chat_db(DB_PATH)
    recover_interrupted_runs(DB_PATH)
    init_trade_case_db(DB_PATH)
    yield


app = FastAPI(title="Deriv Smart Trading Gateway API", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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
async def market(symbol: str) -> dict[str, Any]:
    data = await market_context(symbol.strip().upper())
    return {"market": data}


@app.post("/api/strategy/analyze")
async def strategy(request: StrategyRequest) -> dict[str, Any]:
    market = await market_context(request.symbol.strip().upper())
    closes = market.get("closes") or []
    if len(closes) < 20:
        raise HTTPException(status_code=422, detail="not enough candle data for strategy analysis")
    frame = normalize_price_frame(pd.DataFrame({"close": closes}))
    config = MicroTradeConfig(symbol=request.symbol.strip().upper(), max_trade_amount=request.amount)
    decision = analyze_micro_trade(frame, config)
    budget = budget_guard_check(
        action="execute_simulated_trade",
        amount=request.amount,
        limits=BudgetLimits(
            max_single_trade_amount=request.amount,
            max_daily_trade_budget=max(5.0, request.amount),
            max_total_trade_budget=max(5.0, request.amount),
        ),
        daily_spent=0,
        total_spent=0,
    )
    backtest = backtest_micro_strategy(frame, config, CircuitBreakerConfig(), lookback_bars=8)
    return {
        "symbol": config.symbol,
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
async def chat_stream(request: ChatRequest) -> StreamingResponse:
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
                    },
                )
                yield _sse(_case_updated_event(running_case))
            async for event in stream_multi_agent_chat(
                message=request.message,
                history=history,
                config=config,
                prompts_path=PROMPTS_PATH,
                symbol_override=str(linked_case["symbol"]) if linked_case else None,
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
                        for case_event in _persist_chat_case_evidence(
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
    return {
        "id": case["id"],
        "title": case["title"],
        "objective": case["objective"],
        "symbol": case["symbol"],
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


def _record_case_artifact(
    case_id: str,
    *,
    artifact_type: str,
    actor: str,
    message: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return record_trade_case_artifact(
        DB_PATH,
        case_id,
        artifact_type=artifact_type,
        actor=actor,
        message=message,
        payload=payload,
    )


def _direction_from_answer(answer: str) -> str:
    normalized = answer.upper()
    call = "CALL" in normalized or "看涨" in answer
    put = "PUT" in normalized or "看跌" in answer
    if call == put:
        return "WAIT"
    return "CALL" if call else "PUT"


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
    stance = _direction_from_answer(answer)
    updated: list[dict[str, Any]] = []
    advisor_case = _record_case_artifact(
        case_id,
        artifact_type="advisor",
        actor="advisor_council",
        message="谋士团结论已从经理对话同步",
        payload={
            "question": question,
            "symbol": symbol,
            "stance": stance,
            "confidence": 0.68 if stance in {"CALL", "PUT"} else 0.45,
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
            "session_id": session_id,
        },
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
            "detail": {"blockers": blockers, "warnings": []},
        },
    )
    updated.append(_case_updated_event(workflow_case))
    return updated


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
                "status": row["status"],
                "stage": row["stage"],
                "version": row["version"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    }


@app.post("/api/cases", status_code=201)
def create_case(request: TradeCaseRequest) -> dict[str, Any]:
    case = create_trade_case(
        DB_PATH,
        objective=request.objective,
        symbol=request.symbol.strip().upper(),
        title=request.title,
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
