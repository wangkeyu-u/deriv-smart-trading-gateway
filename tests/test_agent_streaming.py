from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor

import agent_streaming
from agent_streaming import (
    ChatRuntimeConfig,
    create_chat_session,
    list_agent_runs,
    list_chat_sessions,
    load_chat_messages,
    route_agents,
    save_chat_message,
    start_agent_run,
    recover_interrupted_runs,
    stream_multi_agent_chat,
)


def test_chat_history_persists_per_session(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    first = create_chat_session(db_path)
    second = create_chat_session(db_path)
    save_chat_message(db_path, first, "user", "first session")
    save_chat_message(db_path, second, "user", "second session")

    assert [item["content"] for item in load_chat_messages(db_path, first)] == ["first session"]
    assert [item["content"] for item in load_chat_messages(db_path, second)] == ["second session"]


def test_chat_session_list_uses_first_user_message_as_title(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    session_id = create_chat_session(db_path, "Operator conversation")
    save_chat_message(db_path, session_id, "user", "分析 R_75 的风险和机会")
    save_chat_message(db_path, session_id, "assistant", "分析完成")

    sessions = list_chat_sessions(db_path)

    assert sessions[0]["id"] == session_id
    assert sessions[0]["title"] == "分析 R_75 的风险和机会"
    assert sessions[0]["message_count"] == 2
    assert sessions[0]["preview"] == "分析完成"


def test_route_agents_adds_safety_agents_for_trade_intent() -> None:
    route = route_agents("帮我买 R_75，金额 1 美元")
    assert route == ["strategy", "risk", "compliance", "report"]


def test_local_runtime_streams_agent_events_and_answer(tmp_path) -> None:
    prompts = tmp_path / "agent_prompts.json"
    prompts.write_text(
        '{"manager":{"name":"经理","prompt":"总结"},'
        '"strategy":{"name":"策略","prompt":"分析"},'
        '"report":{"name":"报告","prompt":"复盘"}}',
        encoding="utf-8",
    )
    async def collect() -> list[dict]:
        return [
            event
            async for event in stream_multi_agent_chat(
                message="介绍一下你的能力",
                history=[],
                config=ChatRuntimeConfig(provider="local", language="zh"),
                prompts_path=prompts,
            )
        ]

    events = asyncio.run(collect())

    assert events[0]["type"] == "start"
    assert any(event["type"] == "agent_start" for event in events)
    assert any(event["type"] == "agent_done" for event in events)
    deltas = "".join(event["delta"] for event in events if event["type"] == "answer_delta")
    assert "不会自动下单" in deltas
    assert events[-1]["type"] == "done"


def test_routed_agents_run_in_parallel(tmp_path) -> None:
    prompts = tmp_path / "agent_prompts.json"
    prompts.write_text(
        '{"strategy":{"name":"策略","prompt":"分析"},'
        '"risk":{"name":"风控","prompt":"检查"},'
        '"compliance":{"name":"合规","prompt":"检查"},'
        '"report":{"name":"报告","prompt":"总结"}}',
        encoding="utf-8",
    )

    async def collect_until_agents_finish() -> tuple[list[dict], float]:
        events: list[dict] = []
        started = time.perf_counter()
        stream = stream_multi_agent_chat(
            message="帮我买 R_75，金额 1 美元",
            history=[],
            config=ChatRuntimeConfig(provider="local", language="zh"),
            prompts_path=prompts,
        )
        async for event in stream:
            events.append(event)
            if sum(item["type"] == "agent_done" for item in events) == 4:
                elapsed = time.perf_counter() - started
                await stream.aclose()
                return events, elapsed
        raise AssertionError("agents did not finish")

    events, elapsed = asyncio.run(collect_until_agents_finish())
    starts = [index for index, event in enumerate(events) if event["type"] == "agent_start"]
    finishes = [index for index, event in enumerate(events) if event["type"] == "agent_done"]

    assert len(starts) == 4
    assert len(finishes) == 4
    assert max(starts) < min(finishes)
    assert elapsed < 0.24


def test_slow_agent_times_out_without_aborting_other_agents(monkeypatch, tmp_path) -> None:
    prompts = tmp_path / "agent_prompts.json"
    prompts.write_text(
        json.dumps(
            {
                "manager": {"name": "经理", "prompt": "MANAGER_PROMPT"},
                "strategy": {"name": "策略", "prompt": "STRATEGY_PROMPT"},
                "risk": {"name": "风控", "prompt": "RISK_PROMPT"},
                "compliance": {"name": "合规", "prompt": "COMPLIANCE_PROMPT"},
                "report": {"name": "报告", "prompt": "REPORT_PROMPT"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    async def fake_complete(_config, system: str, _user: str) -> str:
        if "RISK_PROMPT" in system:
            await asyncio.sleep(0.2)
        return "独立报告已完成"

    async def fake_stream(_config, _system: str, _user: str):
        yield "经理总结完成"

    monkeypatch.setattr(agent_streaming, "provider_complete", fake_complete)
    monkeypatch.setattr(agent_streaming, "provider_stream", fake_stream)

    async def collect() -> list[dict]:
        return [
            event
            async for event in stream_multi_agent_chat(
                message="帮我买 R_75，金额 1 美元",
                history=[],
                config=ChatRuntimeConfig(
                    provider="openai",
                    api_key="test-key",
                    agent_timeout_seconds=0.1,
                ),
                prompts_path=prompts,
            )
        ]

    events = asyncio.run(collect())
    errors = [event for event in events if event["type"] == "agent_error"]
    done = events[-1]

    assert [(item["agent_id"], item["error_code"]) for item in errors] == [("risk", "timeout")]
    assert sum(event["type"] == "agent_done" for event in events) == 3
    assert done["type"] == "done"
    assert done["failed_agents"] == ["risk"]
    assert set(done["successful_agents"]) == {"strategy", "compliance", "report"}
    assert done["manager_fallback"] is False


def test_market_timeout_degrades_without_aborting_answer(monkeypatch, tmp_path) -> None:
    prompts = tmp_path / "agent_prompts.json"
    prompts.write_text(
        '{"strategy":{"name":"策略","prompt":"分析"},'
        '"market":{"name":"行情","prompt":"检查"},'
        '"report":{"name":"报告","prompt":"总结"}}',
        encoding="utf-8",
    )

    async def slow_market(_symbol: str) -> dict:
        await asyncio.sleep(0.2)
        return {"ok": True}

    monkeypatch.setattr(agent_streaming, "market_context", slow_market)

    async def collect() -> list[dict]:
        return [
            event
            async for event in stream_multi_agent_chat(
                message="检查 R_50 行情走势",
                history=[],
                config=ChatRuntimeConfig(provider="local", tool_timeout_seconds=0.1),
                prompts_path=prompts,
            )
        ]

    events = asyncio.run(collect())
    tool = next(event for event in events if event["type"] == "tool_done")

    assert tool["ok"] is False
    assert tool["error"] == "行情服务响应超时"
    assert events[-1]["type"] == "done"
    assert "行情暂时不可用" in events[-1]["answer"]


def test_process_restart_marks_open_runs_interrupted(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    session_id = create_chat_session(db_path)
    start_agent_run(
        db_path,
        run_id="RUN-OPEN",
        session_id=session_id,
        case_id=None,
        provider="local",
        model="local-rule-engine",
        symbol="R_75",
        route=["strategy", "report"],
    )

    assert recover_interrupted_runs(db_path) == 1
    run = list_agent_runs(db_path)[0]

    assert run["status"] == "interrupted"
    assert run["error"] == "process_restarted"
    assert run["completed_at"] is not None
    assert recover_interrupted_runs(db_path) == 0


def test_chat_memory_handles_concurrent_writers(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    session_id = create_chat_session(db_path)

    def write(index: int) -> None:
        save_chat_message(db_path, session_id, "assistant", f"message-{index}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(24)))

    messages = load_chat_messages(db_path, session_id, limit=40)
    assert len(messages) == 24
    assert {item["content"] for item in messages} == {f"message-{index}" for index in range(24)}
