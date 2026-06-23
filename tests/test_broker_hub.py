from __future__ import annotations

import asyncio

import pytest

import broker_hub
from broker_hub import broker_catalog, get_broker, list_broker_profiles, normalize_account_snapshot, save_broker_profile


def test_catalog_exposes_normalized_multi_broker_capabilities() -> None:
    catalog = broker_catalog()
    ids = {item["id"] for item in catalog}

    assert {"deriv", "alpaca", "oanda", "ibkr", "coinbase", "kraken", "binance"}.issubset(ids)
    assert "equities" in get_broker("ibkr").capabilities
    assert "forex" in get_broker("oanda").capabilities
    assert get_broker("coinbase").connection_test_supported is False
    by_id = {item["id"]: item for item in catalog}
    assert by_id["deriv"]["integration_level"] == "full_adapter"
    assert "live_orders" in by_id["deriv"]["implemented_capabilities"]
    assert by_id["binance"]["integration_level"] == "market_and_account"
    assert "live_orders" not in by_id["binance"]["implemented_capabilities"]
    assert by_id["alpaca"]["implemented_capabilities"] == ["account"]
    assert by_id["coinbase"]["integration_level"] == "market_data_only"
    assert by_id["coinbase"]["implemented_capabilities"] == ["market_data", "paper"]


def test_profiles_persist_metadata_with_one_default(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    first = save_broker_profile(
        db_path,
        broker_id="deriv",
        label="Deriv Demo",
        environment="demo",
        is_default=True,
    )
    second = save_broker_profile(
        db_path,
        broker_id="alpaca",
        label="Alpaca Paper",
        environment="paper",
        is_default=True,
    )
    profiles = list_broker_profiles(db_path)

    assert first["id"] != second["id"]
    assert sum(profile["is_default"] for profile in profiles) == 1
    assert profiles[0]["broker_id"] == "alpaca"


def test_profile_rejects_missing_account_and_secret_persistence(tmp_path) -> None:
    db_path = tmp_path / "gateway.sqlite3"
    with pytest.raises(ValueError, match="account_id"):
        save_broker_profile(
            db_path,
            broker_id="oanda",
            label="OANDA Practice",
            environment="practice",
        )
    with pytest.raises(ValueError, match="secrets cannot be persisted"):
        save_broker_profile(
            db_path,
            broker_id="kraken",
            label="Kraken",
            environment="live",
            settings={"api_secret": "do-not-store"},
        )


def test_connection_diagnostic_contains_unexpected_adapter_failure(monkeypatch) -> None:
    async def fail_adapter(*_args, **_kwargs):
        raise RuntimeError("provider details that must not escape")

    monkeypatch.setattr(broker_hub, "_run_connection_test", fail_adapter)
    result = asyncio.run(
        broker_hub.test_broker_connection(
            broker_id="binance",
            environment="testnet",
            account_id="",
            credentials={"api_key": "test-key", "api_secret": "test-secret"},
        )
    )

    assert result["ok"] is False
    assert result["status"] == "connection_failed"
    assert result["message"] == "Binance connection test failed (RuntimeError)"
    assert "provider details" not in result["message"]


def test_connection_result_contains_normalized_account_snapshot(monkeypatch) -> None:
    async def fake_adapter(*_args, **_kwargs):
        return {
            "id": "paper-account",
            "currency": "USD",
            "balance": "125.50",
            "buying_power": "200.00",
            "positions": [{"symbol": "AAPL", "quantity": "1"}],
            "can_trade": True,
        }

    monkeypatch.setattr(broker_hub, "_run_connection_test", fake_adapter)
    result = asyncio.run(
        broker_hub.test_broker_connection(
            broker_id="alpaca",
            environment="paper",
            account_id="",
            credentials={"api_key": "test-key", "api_secret": "test-secret"},
        )
    )

    assert result["ok"] is True
    assert result["snapshot"] == normalize_account_snapshot(get_broker("alpaca"), result["account"])
    assert result["snapshot"]["position_count"] == 1
    assert result["snapshot"]["balance"] == "125.50"


def test_coinbase_public_market_snapshot_is_normalized(monkeypatch) -> None:
    rows = [[index, 99.0, 101.0, 100.0, 100.0 + index, 1.0] for index in range(60, 0, -1)]

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return rows

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, *, params):
            assert url.endswith("/products/BTC-USD/candles")
            assert params == {"granularity": 60}
            return FakeResponse()

    monkeypatch.setattr(broker_hub.httpx, "AsyncClient", FakeClient)
    snapshot = asyncio.run(broker_hub.public_market_snapshot("coinbase", "BTC-USD"))

    assert snapshot["broker_id"] == "coinbase"
    assert snapshot["symbol"] == "BTC-USD"
    assert snapshot["candle_count"] == 60
    assert snapshot["closes"] == sorted(snapshot["closes"])
    assert snapshot["latest_close"] == 160.0
