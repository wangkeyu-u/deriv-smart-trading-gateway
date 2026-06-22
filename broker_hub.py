"""Multi-broker catalog, connection profiles, and normalized diagnostics.

Secrets are intentionally accepted only for an immediate connection test. The
SQLite profile store contains routing metadata, never API keys or tokens.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx


@dataclass(frozen=True)
class BrokerDefinition:
    id: str
    name: str
    category: str
    regions: tuple[str, ...]
    environments: tuple[str, ...]
    capabilities: tuple[str, ...]
    auth_type: str
    credential_fields: tuple[str, ...]
    account_id_required: bool
    connection_test_supported: bool
    docs_url: str
    notes: str
    integration_level: str
    implemented_capabilities: tuple[str, ...]


BROKERS = (
    BrokerDefinition(
        id="deriv",
        name="Deriv",
        category="Synthetic indices & derivatives",
        regions=("Global where available",),
        environments=("demo", "live"),
        capabilities=("market_data", "account", "positions", "options_contracts", "paper", "live_orders"),
        auth_type="token",
        credential_fields=("api_token", "app_id"),
        account_id_required=False,
        connection_test_supported=True,
        docs_url="https://developers.deriv.com/",
        notes="WebSocket API; demo accounts are recommended for validation.",
        integration_level="full_adapter",
        implemented_capabilities=("market_data", "account", "positions", "paper", "live_orders"),
    ),
    BrokerDefinition(
        id="alpaca",
        name="Alpaca",
        category="US equities & crypto",
        regions=("United States", "Supported international regions"),
        environments=("paper", "live"),
        capabilities=("market_data", "account", "positions", "equities", "crypto", "paper", "live_orders"),
        auth_type="api_key_pair",
        credential_fields=("api_key", "api_secret"),
        account_id_required=False,
        connection_test_supported=True,
        docs_url="https://docs.alpaca.markets/docs/trading-api",
        notes="Paper and live trading use separate API hosts and credentials.",
        integration_level="account_diagnostic",
        implemented_capabilities=("account",),
    ),
    BrokerDefinition(
        id="oanda",
        name="OANDA",
        category="Forex & CFDs",
        regions=("Region-dependent",),
        environments=("practice", "live"),
        capabilities=("market_data", "account", "positions", "forex", "cfd", "paper", "live_orders"),
        auth_type="bearer_token",
        credential_fields=("api_token",),
        account_id_required=True,
        connection_test_supported=True,
        docs_url="https://developer.oanda.com/rest-live-v20/introduction/",
        notes="v20 REST API; instrument availability depends on account region.",
        integration_level="account_diagnostic",
        implemented_capabilities=("account",),
    ),
    BrokerDefinition(
        id="ibkr",
        name="Interactive Brokers",
        category="Multi-asset brokerage",
        regions=("Global where available",),
        environments=("paper", "live"),
        capabilities=("market_data", "account", "positions", "equities", "options", "futures", "forex", "bonds", "paper", "live_orders"),
        auth_type="local_gateway_session",
        credential_fields=(),
        account_id_required=False,
        connection_test_supported=True,
        docs_url="https://ibkrcampus.com/campus/ibkr-api-page/cpapi-v1/",
        notes="Requires an authenticated Client Portal Gateway running locally.",
        integration_level="account_diagnostic",
        implemented_capabilities=("account",),
    ),
    BrokerDefinition(
        id="coinbase",
        name="Coinbase Advanced",
        category="Crypto spot",
        regions=("Supported Coinbase regions",),
        environments=("live",),
        capabilities=("market_data", "account", "positions", "crypto", "live_orders"),
        auth_type="cdp_jwt_key_pair",
        credential_fields=("api_key_name", "private_key"),
        account_id_required=False,
        connection_test_supported=False,
        docs_url="https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/overview",
        notes="Public spot candles are available; private account access still requires a CDP JWT adapter.",
        integration_level="market_data_only",
        implemented_capabilities=("market_data", "paper"),
    ),
    BrokerDefinition(
        id="kraken",
        name="Kraken",
        category="Crypto spot & derivatives",
        regions=("Supported Kraken regions",),
        environments=("live",),
        capabilities=("market_data", "account", "positions", "crypto", "spot", "live_orders"),
        auth_type="signed_api_key",
        credential_fields=("api_key", "api_secret"),
        account_id_required=False,
        connection_test_supported=True,
        docs_url="https://docs.kraken.com/api/",
        notes="Private REST calls require API-Key, API-Sign, and a monotonic nonce.",
        integration_level="market_and_account",
        implemented_capabilities=("market_data", "account", "paper"),
    ),
    BrokerDefinition(
        id="binance",
        name="Binance",
        category="Crypto spot & derivatives",
        regions=("Region-dependent",),
        environments=("testnet", "live"),
        capabilities=("market_data", "account", "positions", "crypto", "spot", "paper", "live_orders"),
        auth_type="hmac_api_key",
        credential_fields=("api_key", "api_secret"),
        account_id_required=False,
        connection_test_supported=True,
        docs_url="https://developers.binance.com/docs/binance-spot-api-docs/rest-api/account-endpoints",
        notes="Availability and product scope depend on the selected regional entity.",
        integration_level="market_and_account",
        implemented_capabilities=("market_data", "account", "paper"),
    ),
)

BROKER_BY_ID = {broker.id: broker for broker in BROKERS}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def broker_catalog() -> list[dict[str, Any]]:
    return [
        {
            **asdict(item),
            "regions": list(item.regions),
            "environments": list(item.environments),
            "capabilities": list(item.capabilities),
            "credential_fields": list(item.credential_fields),
            "implemented_capabilities": list(item.implemented_capabilities),
        }
        for item in BROKERS
    ]


def get_broker(broker_id: str) -> BrokerDefinition:
    broker = BROKER_BY_ID.get(broker_id.strip().lower())
    if broker is None:
        raise ValueError(f"unsupported broker: {broker_id}")
    return broker


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_broker_db(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS broker_profiles (
                id TEXT PRIMARY KEY,
                broker_id TEXT NOT NULL,
                label TEXT NOT NULL,
                environment TEXT NOT NULL,
                account_id TEXT NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0,
                settings_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_broker_profiles_default ON broker_profiles(is_default DESC, updated_at DESC)")


def _profile(row: sqlite3.Row) -> dict[str, Any]:
    try:
        settings = json.loads(str(row["settings_json"] or "{}"))
    except json.JSONDecodeError:
        settings = {}
    return {
        "id": row["id"],
        "broker_id": row["broker_id"],
        "label": row["label"],
        "environment": row["environment"],
        "account_id": row["account_id"],
        "is_default": bool(row["is_default"]),
        "settings": settings if isinstance(settings, dict) else {},
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_broker_profiles(db_path: Path) -> list[dict[str, Any]]:
    init_broker_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM broker_profiles ORDER BY is_default DESC, updated_at DESC").fetchall()
    return [_profile(row) for row in rows]


def save_broker_profile(
    db_path: Path,
    *,
    broker_id: str,
    label: str,
    environment: str,
    account_id: str = "",
    is_default: bool = False,
    settings: dict[str, Any] | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    broker = get_broker(broker_id)
    if environment not in broker.environments:
        raise ValueError(f"unsupported {broker.name} environment: {environment}")
    if broker.account_id_required and not account_id.strip():
        raise ValueError(f"account_id is required for {broker.name}")
    safe_settings = settings or {}
    forbidden = {"secret", "token", "password", "private_key", "api_key"}
    if any(any(part in key.casefold() for part in forbidden) for key in safe_settings):
        raise ValueError("secrets cannot be persisted in broker profile settings")
    now = _now()
    item_id = profile_id or f"BP-{uuid.uuid4().hex[:12].upper()}"
    init_broker_db(db_path)
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if is_default:
            conn.execute("UPDATE broker_profiles SET is_default = 0")
        existing = conn.execute("SELECT created_at FROM broker_profiles WHERE id = ?", (item_id,)).fetchone()
        created_at = str(existing["created_at"]) if existing else now
        conn.execute(
            """
            INSERT INTO broker_profiles (
                id, broker_id, label, environment, account_id, is_default,
                settings_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                broker_id = excluded.broker_id, label = excluded.label,
                environment = excluded.environment, account_id = excluded.account_id,
                is_default = excluded.is_default, settings_json = excluded.settings_json,
                updated_at = excluded.updated_at
            """,
            (item_id, broker.id, label.strip() or broker.name, environment, account_id.strip(), int(is_default), json.dumps(safe_settings), created_at, now),
        )
        row = conn.execute("SELECT * FROM broker_profiles WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise RuntimeError("broker profile was not saved")
    return _profile(row)


def delete_broker_profile(db_path: Path, profile_id: str) -> bool:
    init_broker_db(db_path)
    with _connect(db_path) as conn:
        result = conn.execute("DELETE FROM broker_profiles WHERE id = ?", (profile_id,))
    return result.rowcount == 1


def _required_credentials(broker: BrokerDefinition, credentials: dict[str, str]) -> None:
    missing = [field for field in broker.credential_fields if not str(credentials.get(field) or "").strip()]
    if broker.id == "deriv" and missing == ["app_id"]:
        missing = []
    if missing:
        raise ValueError(f"missing credentials: {', '.join(missing)}")


async def test_broker_connection(
    *,
    broker_id: str,
    environment: str,
    account_id: str,
    credentials: dict[str, str],
) -> dict[str, Any]:
    broker = get_broker(broker_id)
    if environment not in broker.environments:
        raise ValueError(f"unsupported {broker.name} environment: {environment}")
    if not broker.connection_test_supported:
        return {"ok": False, "broker_id": broker.id, "status": "adapter_required", "message": broker.notes}
    _required_credentials(broker, credentials)
    started = time.perf_counter()
    try:
        account = await _run_connection_test(broker, environment, account_id.strip(), credentials)
    except httpx.HTTPStatusError as exc:
        message = f"{broker.name} rejected the connection (HTTP {exc.response.status_code})"
        return {"ok": False, "broker_id": broker.id, "status": "connection_failed", "message": message, "latency_ms": round((time.perf_counter() - started) * 1000)}
    except httpx.RequestError as exc:
        message = f"Could not reach {broker.name} ({type(exc).__name__})"
        return {"ok": False, "broker_id": broker.id, "status": "connection_failed", "message": message, "latency_ms": round((time.perf_counter() - started) * 1000)}
    except (ValueError, KeyError) as exc:
        return {"ok": False, "broker_id": broker.id, "status": "connection_failed", "message": str(exc), "latency_ms": round((time.perf_counter() - started) * 1000)}
    except Exception as exc:
        # Broker clients and crypto libraries raise provider-specific exceptions.
        # Keep that failure inside the diagnostic boundary without exposing secrets.
        message = f"{broker.name} connection test failed ({type(exc).__name__})"
        return {"ok": False, "broker_id": broker.id, "status": "connection_failed", "message": message, "latency_ms": round((time.perf_counter() - started) * 1000)}
    return {
        "ok": True,
        "broker_id": broker.id,
        "status": "connected",
        "environment": environment,
        "account": account,
        "snapshot": normalize_account_snapshot(broker, account),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "checked_at": _now(),
    }


def normalize_account_snapshot(broker: BrokerDefinition, account: dict[str, Any]) -> dict[str, Any]:
    """Map provider-specific diagnostics into one safe operator-facing shape."""
    positions = account.get("positions") if isinstance(account.get("positions"), list) else []
    balance = account.get("balance", account.get("cash_balance"))
    return {
        "broker_id": broker.id,
        "account_id": account.get("id") or account.get("loginid") or account.get("account_id"),
        "currency": account.get("currency"),
        "status": account.get("status") or ("connected" if account.get("connected", True) else "disconnected"),
        "balance": balance,
        "buying_power": account.get("buying_power"),
        "net_equity": account.get("net_equity"),
        "position_count": account.get("position_count", account.get("open_positions", len(positions))),
        "asset_count": account.get("asset_count"),
        "can_trade": account.get("can_trade"),
        "positions": positions[:12],
    }


async def public_market_snapshot(broker_id: str, symbol: str) -> dict[str, Any]:
    """Return normalized public candles for brokers that expose them without auth."""
    broker = get_broker(broker_id)
    clean_symbol = symbol.strip().upper()
    timeout = httpx.Timeout(8.0)
    if broker.id == "binance":
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": clean_symbol.replace("-", ""), "interval": "1m", "limit": 60},
            )
            response.raise_for_status()
            rows = response.json()
        closes = [float(row[4]) for row in rows]
    elif broker.id == "coinbase":
        product_id = clean_symbol if "-" in clean_symbol else clean_symbol.replace("USD", "-USD")
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"https://api.exchange.coinbase.com/products/{product_id}/candles",
                params={"granularity": 60},
            )
            response.raise_for_status()
            rows = sorted(response.json()[:60], key=lambda row: row[0])
        closes = [float(row[4]) for row in rows]
    elif broker.id == "kraken":
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                "https://api.kraken.com/0/public/OHLC",
                params={"pair": clean_symbol, "interval": 1},
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("error"):
            raise ValueError("; ".join(payload["error"]))
        result = payload.get("result") or {}
        rows = next((value for key, value in result.items() if key != "last"), [])[-60:]
        closes = [float(row[4]) for row in rows]
    else:
        raise ValueError(
            f"{broker.name} market data requires an authenticated adapter session; connect the account in Broker Hub first"
        )
    if len(closes) < 2:
        raise ValueError(f"{broker.name} returned insufficient candle data for {clean_symbol}")
    change = ((closes[-1] - closes[0]) / closes[0] * 100) if closes[0] else 0.0
    return {
        "broker_id": broker.id,
        "symbol": clean_symbol,
        "tick": {"quote": closes[-1], "epoch": int(time.time())},
        "candle_count": len(closes),
        "window_change_pct": change,
        "latest_close": closes[-1],
        "closes": closes,
        "ok": True,
    }


async def _run_connection_test(broker: BrokerDefinition, environment: str, account_id: str, credentials: dict[str, str]) -> dict[str, Any]:
    timeout = httpx.Timeout(8.0)
    if broker.id == "deriv":
        from server import DerivWebSocketClient, account_type_from_authorize, summarize_portfolio

        async with DerivWebSocketClient(app_id=credentials.get("app_id") or "1089", api_token=credentials["api_token"]) as client:
            auth = client.authorization or {}
            balance_response = await client.request({"balance": 1, "subscribe": 0})
            portfolio_response = await client.request({"portfolio": 1})
            balance = balance_response.get("balance") or {}
            portfolio = summarize_portfolio(portfolio_response)
            cash_balance = float(balance.get("balance") or 0)
            return {
                "id": auth.get("loginid") or balance.get("loginid"),
                "currency": auth.get("currency") or balance.get("currency"),
                "type": account_type_from_authorize(auth),
                "balance": cash_balance,
                "net_equity": cash_balance + portfolio["total_open_buy_price"],
                "position_count": portfolio["open_contract_count"],
                "positions": portfolio["contracts"],
                "status": "connected",
                "can_trade": True,
            }
    if broker.id == "alpaca":
        host = "https://paper-api.alpaca.markets" if environment == "paper" else "https://api.alpaca.markets"
        headers = {"APCA-API-KEY-ID": credentials["api_key"], "APCA-API-SECRET-KEY": credentials["api_secret"]}
        async with httpx.AsyncClient(timeout=timeout) as client:
            account_response = await client.get(f"{host}/v2/account", headers=headers)
            positions_response = await client.get(f"{host}/v2/positions", headers=headers)
            account_response.raise_for_status()
            positions_response.raise_for_status()
            data = account_response.json()
            positions = positions_response.json()
        return {
            "id": data.get("id"),
            "currency": data.get("currency"),
            "status": data.get("status"),
            "balance": data.get("cash"),
            "net_equity": data.get("equity"),
            "buying_power": data.get("buying_power"),
            "can_trade": not data.get("trading_blocked", False),
            "position_count": len(positions),
            "positions": [
                {"symbol": item.get("symbol"), "quantity": item.get("qty"), "market_value": item.get("market_value"), "unrealized_pnl": item.get("unrealized_pl")}
                for item in positions[:12]
            ],
        }
    if broker.id == "oanda":
        if not account_id:
            raise ValueError("account_id is required for OANDA")
        host = "https://api-fxpractice.oanda.com" if environment == "practice" else "https://api-fxtrade.oanda.com"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{host}/v3/accounts/{account_id}/summary", headers={"Authorization": f"Bearer {credentials['api_token']}"})
            response.raise_for_status()
            data = response.json().get("account") or {}
        return {"id": data.get("id") or account_id, "currency": data.get("currency"), "balance": data.get("balance"), "net_equity": data.get("NAV"), "open_positions": data.get("openPositionCount"), "status": "connected", "can_trade": True}
    if broker.id == "ibkr":
        host = "https://localhost:5000/v1/api"
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            response = await client.get(f"{host}/iserver/auth/status")
            response.raise_for_status()
            data = response.json()
        if not data.get("authenticated"):
            raise ValueError("IBKR Client Portal Gateway is running but not authenticated")
        return {"authenticated": True, "connected": data.get("connected"), "competing": data.get("competing"), "status": "connected" if data.get("connected") else "authenticated", "can_trade": bool(data.get("connected"))}
    if broker.id == "kraken":
        path = "/0/private/Balance"
        nonce = str(int(time.time() * 1000))
        body = {"nonce": nonce}
        encoded = (nonce + urlencode(body)).encode()
        message = path.encode() + hashlib.sha256(encoded).digest()
        signature = base64.b64encode(hmac.new(base64.b64decode(credentials["api_secret"]), message, hashlib.sha512).digest()).decode()
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"https://api.kraken.com{path}", data=body, headers={"API-Key": credentials["api_key"], "API-Sign": signature})
            response.raise_for_status()
            data = response.json()
        if data.get("error"):
            raise ValueError("; ".join(data["error"]))
        balances = data.get("result") or {}
        positions = [{"symbol": asset, "quantity": amount} for asset, amount in sorted(balances.items()) if float(amount or 0) != 0][:12]
        return {"asset_count": len(positions), "position_count": len(positions), "positions": positions, "status": "connected", "can_trade": True}
    if broker.id == "binance":
        host = "https://testnet.binance.vision" if environment == "testnet" else "https://api.binance.com"
        query = urlencode({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
        signature = hmac.new(credentials["api_secret"].encode(), query.encode(), hashlib.sha256).hexdigest()
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{host}/api/v3/account?{query}&signature={signature}", headers={"X-MBX-APIKEY": credentials["api_key"]})
            response.raise_for_status()
            data = response.json()
        positions = [
            {"symbol": item.get("asset"), "available": item.get("free"), "locked": item.get("locked")}
            for item in (data.get("balances") or [])
            if float(item.get("free") or 0) != 0 or float(item.get("locked") or 0) != 0
        ][:12]
        return {"account_type": data.get("accountType"), "can_trade": data.get("canTrade"), "asset_count": len(positions), "position_count": len(positions), "positions": positions, "status": "connected"}
    raise ValueError(f"connection adapter is not installed for {broker.name}")
