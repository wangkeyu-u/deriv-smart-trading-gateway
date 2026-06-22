from __future__ import annotations

from fastapi.testclient import TestClient

import agent_streaming
import gateway_api
from trade_cases import control_trade_case, get_trade_case, record_trade_case_artifact


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


def test_non_deriv_market_uses_selected_broker_adapter(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")

    async def fake_public_market(broker_id: str, symbol: str) -> dict:
        return {
            "broker_id": broker_id,
            "symbol": symbol,
            "tick": {"quote": 65000},
            "candle_count": 60,
            "window_change_pct": 1.2,
            "latest_close": 65000,
            "closes": [64000, 65000],
            "ok": True,
        }

    monkeypatch.setattr(gateway_api, "public_market_snapshot", fake_public_market)
    with TestClient(gateway_api.app) as client:
        response = client.get("/api/market/BTCUSDT?broker_id=binance")

    assert response.status_code == 200
    assert response.json()["market"]["broker_id"] == "binance"
    assert response.json()["market"]["symbol"] == "BTCUSDT"


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


def test_spot_strategy_uses_buy_sell_hold_vocabulary(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")

    async def fake_public_market(broker_id: str, symbol: str) -> dict:
        closes = [100 + index * 0.08 for index in range(60)]
        return {
            "broker_id": broker_id,
            "symbol": symbol,
            "tick": {"quote": closes[-1]},
            "candle_count": len(closes),
            "window_change_pct": 4.72,
            "latest_close": closes[-1],
            "closes": closes,
            "ok": True,
        }

    monkeypatch.setattr(gateway_api, "public_market_snapshot", fake_public_market)
    with TestClient(gateway_api.app) as client:
        response = client.post(
            "/api/strategy/analyze",
            json={"broker_id": "binance", "symbol": "BTCUSDT", "amount": 1},
        )

    assert response.status_code == 200
    assert response.json()["broker_id"] == "binance"
    assert response.json()["decision"]["action"] in {"BUY", "SELL", "HOLD"}


def test_strategy_circuit_breaker_overrides_direction(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")

    async def fake_public_market(_broker_id: str, symbol: str) -> dict:
        closes = [100 + index * 0.1 for index in range(60)]
        return {"symbol": symbol, "closes": closes, "candle_count": 60, "latest_close": closes[-1], "ok": True}

    monkeypatch.setattr(gateway_api, "public_market_snapshot", fake_public_market)
    monkeypatch.setattr(
        gateway_api,
        "backtest_micro_strategy",
        lambda *_args, **_kwargs: {"ok": True, "summary": {"halted": True, "halt_reason": "max_consecutive_losses"}},
    )
    with TestClient(gateway_api.app) as client:
        response = client.post(
            "/api/strategy/analyze",
            json={"broker_id": "binance", "symbol": "BTCUSDT", "amount": 1},
        )

    decision = response.json()["decision"]
    assert decision["action"] == "HOLD"
    assert "circuit_breaker_halted" in decision["blockers"]


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


def test_trade_case_persists_selected_broker(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")
    with TestClient(gateway_api.app) as client:
        created = client.post(
            "/api/cases",
            json={"objective": "Validate BTC momentum", "symbol": "BTCUSDT", "broker_id": "binance"},
        )
        listed = client.get("/api/cases")

    assert created.status_code == 201
    assert created.json()["case"]["broker_id"] == "binance"
    assert listed.json()["cases"][0]["broker_id"] == "binance"


def test_broker_profile_and_connection_routes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")

    async def fake_test(**kwargs) -> dict:
        return {"ok": True, "broker_id": kwargs["broker_id"], "status": "connected", "latency_ms": 7}

    monkeypatch.setattr(gateway_api, "test_broker_connection", fake_test)
    with TestClient(gateway_api.app) as client:
        catalog = client.get("/api/brokers")
        saved = client.put(
            "/api/broker-profiles",
            json={"broker_id": "alpaca", "label": "Paper", "environment": "paper", "is_default": True},
        )
        tested = client.post(
            "/api/brokers/alpaca/test",
            json={"environment": "paper", "credentials": {"api_key": "key", "api_secret": "secret"}},
        )

    assert catalog.status_code == 200
    assert len(catalog.json()["brokers"]) >= 7
    assert saved.status_code == 200
    assert saved.json()["profile"]["is_default"] is True
    assert tested.json()["broker_id"] == "alpaca"


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
    assert detail["case"]["stage"] == "micro_backtest"
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


def test_risk_policy_api_persists_shared_limits(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")
    with TestClient(gateway_api.app) as client:
        initial = client.get("/api/risk-policy")
        policy = initial.json()["policy"]
        policy.update(
            {
                "max_single_trade_amount": 0.5,
                "max_daily_trade_budget": 2.0,
                "max_total_trade_budget": 8.0,
            }
        )
        saved = client.put("/api/risk-policy", json=policy)
        reloaded = client.get("/api/risk-policy")

    assert initial.status_code == 200
    assert saved.status_code == 200
    assert reloaded.json()["policy"]["max_single_trade_amount"] == 0.5


def _ready_case(db_path, case_id: str) -> dict:
    artifacts = (
        (
            "advisor",
            {"symbol": "R_75", "stance": "CALL", "confidence": 0.8, "consensus": "Momentum supports a small paper validation."},
        ),
        (
            "market",
            {
                "symbol": "R_75",
                "latest_close": 101.25,
                "latest_timestamp": "2026-06-19T12:00:00+00:00",
                "candle_count": 60,
                "integrity": {"ok": True, "fresh": True, "issues": []},
            },
        ),
        (
            "micro_strategy",
            {
                "config": {"symbol": "R_75", "max_trade_amount": 1.0},
                "decision": {"action": "CALL", "confidence": 0.74},
                "budget_guard": {"ok": True, "reason": "within_budget"},
                "backtest": {"summary": {"trade_count": 8, "wins": 5, "losses": 3, "win_rate": 0.625, "total_pnl": 0.08, "halted": False}},
            },
        ),
        ("risk", {"ok": True, "blockers": [], "warnings": []}),
        (
            "pending_trade",
            {"symbol": "R_75", "contract_type": "CALL", "amount": 1.0, "duration": 5, "duration_unit": "t", "allow_live": False},
        ),
    )
    case = None
    for artifact_type, payload in artifacts:
        case = record_trade_case_artifact(
            db_path,
            case_id,
            artifact_type=artifact_type,
            actor="test",
            message=f"add {artifact_type}",
            payload=payload,
        )
    assert case is not None
    return case


def test_decision_inbox_approves_current_evidence_without_executing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")
    with TestClient(gateway_api.app) as client:
        created = client.post(
            "/api/cases",
            json={"objective": "Validate a small R_75 opportunity", "symbol": "R_75"},
        ).json()["case"]
        ready = _ready_case(gateway_api.DB_PATH, created["id"])
        inbox = client.get("/api/decisions")
        approved = client.post(
            f"/api/decisions/{created['id']}/action",
            json={"action": "approve", "note": "Paper plan reviewed", "expected_version": ready["version"]},
        )

    assert inbox.status_code == 200
    assert inbox.json()["items"][0]["state"] == "ready"
    assert approved.status_code == 200
    assert approved.json()["item"]["state"] == "approved"
    artifacts = get_trade_case(gateway_api.DB_PATH, created["id"])["context"]["artifacts"]
    assert artifacts["operator_decision"]["payload"]["decision"] == "approved"
    assert "execution" not in artifacts
    assert "trade_receipt" not in artifacts


def test_new_evidence_invalidates_prior_operator_decision(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gateway_api, "DB_PATH", tmp_path / "gateway.sqlite3")
    with TestClient(gateway_api.app) as client:
        created = client.post(
            "/api/cases",
            json={"objective": "Validate R_75", "symbol": "R_75"},
        ).json()["case"]
        ready = _ready_case(gateway_api.DB_PATH, created["id"])
        approved = client.post(
            f"/api/decisions/{created['id']}/action",
            json={"action": "approve", "expected_version": ready["version"]},
        ).json()["item"]
        record_trade_case_artifact(
            gateway_api.DB_PATH,
            created["id"],
            artifact_type="market",
            actor="market_agent",
            message="new market evidence",
            payload={"symbol": "R_75", "latest_close": 99.5, "candle_count": 60, "integrity": {"ok": True, "fresh": True}},
        )
        refreshed = client.get("/api/decisions").json()["items"][0]

    assert approved["state"] == "approved"
    assert refreshed["state"] == "ready"
    assert refreshed["case"]["version"] > refreshed["decision"]["operator_decision"]["version"]
