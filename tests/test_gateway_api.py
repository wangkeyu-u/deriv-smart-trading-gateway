from __future__ import annotations

from fastapi.testclient import TestClient

import agent_streaming
import gateway_api
from trade_cases import control_trade_case


def test_health_and_local_stream(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")
    with TestClient(gateway_api.app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["streaming"] == "sse"

        response = client.post(
            "/api/chat/stream",
            json={"message": "介绍一下你的能力", "provider": "local", "language": "zh"},
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert '"type": "answer_delta"' in response.text
        assert '"type": "done"' in response.text

        sessions = client.get("/api/chat/sessions")
        assert sessions.status_code == 200
        assert sessions.json()["sessions"][0]["title"] == "介绍一下你的能力"

        runs = client.get("/api/runs")
        assert runs.status_code == 200
        latest = runs.json()["runs"][0]
        assert latest["id"].startswith("RUN-")
        assert latest["status"] == "completed"
        assert latest["elapsed_ms"] > 0
        assert len(latest["spans"]) == 2


def test_provider_requires_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")
    with TestClient(gateway_api.app) as client:
        response = client.post(
            "/api/chat/stream",
            json={"message": "hello", "provider": "openai"},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "api_key is required for the selected provider"


def test_market_endpoint_returns_requested_symbol(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")

    async def fake_market(symbol: str) -> dict:
        return {
            "symbol": symbol,
            "tick": {"quote": 101.25},
            "candle_count": 60,
            "window_change_pct": 0.42,
            "latest_close": 101.25,
            "closes": [100.0, 101.25],
            "ok": True,
        }

    monkeypatch.setattr(gateway_api, "market_context", fake_market)
    with TestClient(gateway_api.app) as client:
        response = client.get("/api/market/R_75")

    assert response.status_code == 200
    assert response.json()["market"]["symbol"] == "R_75"
    assert response.json()["market"]["closes"][-1] == 101.25


def test_strategy_endpoint_runs_budget_and_paper_analysis(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")

    async def fake_market(symbol: str) -> dict:
        closes = [100 + index * 0.08 for index in range(60)]
        return {
            "symbol": symbol,
            "tick": {"quote": closes[-1]},
            "candle_count": len(closes),
            "window_change_pct": 4.72,
            "latest_close": closes[-1],
            "closes": closes,
            "ok": True,
        }

    monkeypatch.setattr(gateway_api, "market_context", fake_market)
    with TestClient(gateway_api.app) as client:
        response = client.post("/api/strategy/analyze", json={"symbol": "R_50", "amount": 1})

    payload = response.json()
    assert response.status_code == 200
    assert payload["symbol"] == "R_50"
    assert payload["decision"]["action"] in {"CALL", "WAIT"}
    assert payload["budget"]["ok"] is True
    assert payload["backtest"]["ok"] is True
    assert "closes" not in payload["market"]


def test_trade_case_can_be_created_and_inspected(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")
    with TestClient(gateway_api.app) as client:
        created = client.post(
            "/api/cases",
            json={"objective": "分析 R_25 的短线机会", "symbol": "r_25", "title": "R25 review"},
        )
        case_id = created.json()["case"]["id"]
        detail = client.get(f"/api/cases/{case_id}")

    assert created.status_code == 201
    assert created.json()["case"]["symbol"] == "R_25"
    assert detail.status_code == 200
    assert detail.json()["decision"]["status"] == "not_started"
    assert detail.json()["events"][0]["event_type"] == "created"


def test_linked_chat_persists_agent_evidence_and_streams_case_updates(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")

    async def fake_market(symbol: str) -> dict:
        closes = [100 + index * 0.05 for index in range(60)]
        return {
            "symbol": symbol,
            "tick": {"quote": closes[-1], "epoch": 1_780_000_000},
            "candle_count": len(closes),
            "window_change_pct": 2.95,
            "latest_close": closes[-1],
            "closes": closes,
            "ok": True,
        }

    monkeypatch.setattr(agent_streaming, "market_context", fake_market)
    with TestClient(gateway_api.app) as client:
        created = client.post(
            "/api/cases",
            json={"objective": "分析 R_25 短线机会", "symbol": "R_25", "title": "R25 sync"},
        ).json()["case"]
        response = client.post(
            "/api/chat/stream",
            json={
                "message": "检查 R_100 行情走势和交易风险，但以绑定任务为准",
                "case_id": created["id"],
                "provider": "local",
                "language": "zh",
            },
        )
        detail = client.get(f"/api/cases/{created['id']}").json()

    assert response.status_code == 200
    assert response.text.count('"type": "case_updated"') >= 5
    assert '"symbol": "R_25"' in response.text
    artifacts = detail["case"]["context"]["artifacts"]
    assert {"advisor", "market", "risk", "workflow_run"}.issubset(artifacts)
    assert "pending_trade" not in artifacts
    assert artifacts["market"]["payload"]["symbol"] == "R_25"
    assert detail["case"]["stage"] == "risk_review"
    assert detail["decision"]["gate"]["ok"] is False
    assert detail["decision"]["workflow_step"] == "micro_backtest"


def test_linked_chat_rejects_unknown_or_paused_case(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")
    with TestClient(gateway_api.app) as client:
        missing = client.post(
            "/api/chat/stream",
            json={"message": "分析行情", "case_id": "TC-MISSING", "provider": "local"},
        )
        created = client.post(
            "/api/cases",
            json={"objective": "暂停后不得写入", "symbol": "R_75"},
        ).json()["case"]
        control_trade_case(
            gateway_api.DB_PATH,
            created["id"],
            "pause",
            expected_version=created["version"],
        )
        paused = client.post(
            "/api/chat/stream",
            json={"message": "分析行情", "case_id": created["id"], "provider": "local"},
        )

    assert missing.status_code == 404
    assert paused.status_code == 409
    assert "resume it before running agents" in paused.json()["detail"]
