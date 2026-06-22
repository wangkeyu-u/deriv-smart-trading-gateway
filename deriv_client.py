"""Shared Deriv WebSocket client and market-data helpers.

Extracted from server.py so that agent_streaming.py (and other modules)
can use the Deriv API client without importing the MCP server itself.
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
from datetime import datetime, timezone
from typing import Any

import certifi
import pandas as pd
import websockets
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from typing_extensions import Annotated
from websockets.exceptions import ConnectionClosed, WebSocketException

# ---------------------------------------------------------------------------
# Constants (kept in sync with server.py)
# ---------------------------------------------------------------------------
APP_ID = os.getenv("DERIV_APP_ID", "1089")
DERIV_WS_URL_TEMPLATE = os.getenv(
    "DERIV_WS_URL_TEMPLATE",
    "wss://ws.derivws.com/websockets/v3?app_id={app_id}",
)
REQUEST_TIMEOUT_SECONDS = 5.0
SUBSCRIPTION_SAMPLE_SIZE = 5

Granularity = int  # 60 | 300 | 3600 – kept as int for flexibility


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class GatewayError(Exception):
    """Base error for gateway failures."""


class DerivAPIError(GatewayError):
    """Deriv returned an application-level error payload."""


class DerivTimeoutError(GatewayError):
    """Deriv did not return the expected response in time."""


# ---------------------------------------------------------------------------
# Helpers (pure, no WebSocket state)
# ---------------------------------------------------------------------------
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_secret(value: str | None) -> str | None:
    if not value:
        return value
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-3:]}"


def account_type_from_authorize(authorize: dict[str, Any]) -> str:
    loginid = str(authorize.get("loginid") or authorize.get("account") or "")
    landing_company = str(authorize.get("landing_company_name") or "").lower()
    if loginid.upper().startswith("VRTC") or "virtual" in landing_company:
        return "demo"
    if loginid:
        return "live"
    return "unknown"


def enforce_demo_or_explicit_live(authorize: dict[str, Any], allow_live: bool) -> str:
    account_type = account_type_from_authorize(authorize)
    if account_type == "live" and not allow_live:
        raise DerivAPIError(
            "Live account execution is blocked by default. Use a demo token, "
            "or explicitly set allow_live=true after human confirmation."
        )
    return account_type


def clean_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def ok_response(tool: str, data: dict[str, Any]) -> str:
    return clean_json(
        {
            "ok": True,
            "tool": tool,
            "timestamp": utc_now_iso(),
            "data": data,
        }
    )


def error_response(tool: str, error: Exception | str) -> str:
    if isinstance(error, ValidationError):
        message = "Input validation failed"
        details: Any = error.errors()
        error_type = "validation_error"
    else:
        message = str(error)
        details = None
        error_type = error.__class__.__name__ if isinstance(error, Exception) else "error"

    return clean_json(
        {
            "ok": False,
            "tool": tool,
            "timestamp": utc_now_iso(),
            "error": {
                "type": error_type,
                "message": message,
                "details": details,
            },
        }
    )


def deriv_error_message(response: dict[str, Any]) -> str:
    error = response.get("error") or {}
    code = error.get("code", "DerivAPIError")
    message = error.get("message", "Deriv returned an error response")
    return f"{code}: {message}"


# ---------------------------------------------------------------------------
# WebSocket client
# ---------------------------------------------------------------------------
class DerivWebSocketClient:
    """Async Deriv WebSocket client with req_id multiplexing and retries."""

    def __init__(
        self,
        *,
        app_id: str = APP_ID,
        api_token: str | None = None,
        timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
        max_retries: int = 2,
    ) -> None:
        self.app_id = app_id
        self.api_token = api_token
        self.timeout_seconds = min(timeout_seconds, REQUEST_TIMEOUT_SECONDS)
        self.max_retries = max_retries
        self.url = DERIV_WS_URL_TEMPLATE.format(app_id=app_id)
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._receiver_task: asyncio.Task[None] | None = None
        self._req_ids = _count(1)
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._subscriptions: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._request_lock = asyncio.Lock()
        self._authorized = False
        self.authorization: dict[str, Any] | None = None

    async def __aenter__(self) -> "DerivWebSocketClient":
        await self._connect_and_authorize()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._receiver_task:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass
            self._receiver_task = None

        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()
        self._subscriptions.clear()

        if self._ws:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=self.timeout_seconds)
            except Exception:
                pass
            self._ws = None
        self._authorized = False
        self.authorization = None

    # -- internal connect / authorize ----------------------------------------
    async def _connect_and_authorize(self) -> None:
        for attempt in range(self.max_retries + 1):
            try:
                await self._connect_once()
                if self.api_token:
                    await self._authorize_once()
                return
            except (ConnectionClosed, OSError, TimeoutError, WebSocketException, DerivTimeoutError):
                await self.close()
                if attempt >= self.max_retries:
                    raise DerivTimeoutError("Unable to establish Deriv WebSocket connection")
                await asyncio.sleep(self._backoff(attempt))

    async def _connect_once(self) -> None:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        self._ws = await asyncio.wait_for(
            websockets.connect(
                self.url,
                ping_interval=20,
                close_timeout=self.timeout_seconds,
                ssl=ssl_context,
            ),
            timeout=self.timeout_seconds,
        )
        self._receiver_task = asyncio.create_task(self._receiver_loop())

    async def _authorize_once(self) -> None:
        if not self.api_token:
            return
        response = await self._request_once({"authorize": self.api_token})
        if response.get("error"):
            raise DerivAPIError(deriv_error_message(response))
        self._authorized = True
        self.authorization = response.get("authorize") or {}

    async def _receiver_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw_message in self._ws:
                try:
                    message = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue

                req_id = message.get("req_id")
                if isinstance(req_id, int) and req_id in self._pending:
                    future = self._pending.pop(req_id)
                    if not future.done():
                        future.set_result(message)
                    continue

                subscription_id = (message.get("subscription") or {}).get("id")
                if subscription_id and subscription_id in self._subscriptions:
                    await self._subscriptions[subscription_id].put(message)
        except asyncio.CancelledError:
            raise
        except (ConnectionClosed, Exception) as exc:
            self._fail_pending(exc)

    def _fail_pending(self, exc: BaseException) -> None:
        for req_id, future in list(self._pending.items()):
            if not future.done():
                future.set_exception(exc)
            self._pending.pop(req_id, None)

    # -- public request API -------------------------------------------------
    async def request(
        self,
        payload: dict[str, Any],
        *,
        retries: int | None = None,
        allow_deriv_error: bool = False,
    ) -> dict[str, Any]:
        attempts = self.max_retries if retries is None else retries
        for attempt in range(attempts + 1):
            try:
                if self._ws is None:
                    await self._connect_and_authorize()
                response = await self._request_once(payload)
                if response.get("error") and not allow_deriv_error:
                    raise DerivAPIError(deriv_error_message(response))
                return response
            except DerivAPIError:
                raise
            except (ConnectionClosed, OSError, TimeoutError, WebSocketException, DerivTimeoutError):
                await self.close()
                if attempt >= attempts:
                    raise DerivTimeoutError("Deriv request timed out or the WebSocket closed")
                await asyncio.sleep(self._backoff(attempt))

        raise DerivTimeoutError("Deriv request failed after retries")

    async def _request_once(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._ws is None:
            raise DerivTimeoutError("WebSocket is not connected")

        async with self._request_lock:
            req_id = next(self._req_ids)
            request_payload = dict(payload)
            request_payload["req_id"] = req_id
            loop = asyncio.get_running_loop()
            future: asyncio.Future[dict[str, Any]] = loop.create_future()
            self._pending[req_id] = future

            try:
                await asyncio.wait_for(
                    self._ws.send(json.dumps(request_payload)),
                    timeout=self.timeout_seconds,
                )
                return await asyncio.wait_for(future, timeout=self.timeout_seconds)
            except asyncio.TimeoutError as exc:
                raise DerivTimeoutError("Timed out waiting for Deriv response") from exc
            finally:
                self._pending.pop(req_id, None)

    async def collect_subscription(
        self,
        subscription_id: str,
        *,
        limit: int = SUBSCRIPTION_SAMPLE_SIZE,
    ) -> list[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscriptions[subscription_id] = queue
        messages: list[dict[str, Any]] = []

        try:
            while len(messages) < limit:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=self.timeout_seconds)
                except asyncio.TimeoutError:
                    break
                messages.append(message)
        finally:
            self._subscriptions.pop(subscription_id, None)
            try:
                await self.request({"forget": subscription_id}, retries=0, allow_deriv_error=True)
            except Exception:
                pass

        return messages

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(0.25 * (2**attempt), 2.0)


# ---------------------------------------------------------------------------
# Public market-data helpers
# ---------------------------------------------------------------------------
def extract_tick(message: dict[str, Any]) -> dict[str, Any]:
    tick = message.get("tick") or {}
    epoch = tick.get("epoch")
    return {
        "symbol": tick.get("symbol"),
        "quote": tick.get("quote"),
        "epoch": epoch,
        "timestamp": datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch else None,
        "pip_size": tick.get("pip_size"),
        "id": tick.get("id"),
    }


def normalize_candles(response: dict[str, Any]) -> list[dict[str, Any]]:
    candles = response.get("candles") or []
    if not candles:
        return []

    frame = pd.DataFrame(candles)
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "volume" not in frame:
        frame["volume"] = 0
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0)
    frame["epoch"] = pd.to_numeric(frame["epoch"], errors="coerce").astype("Int64")
    frame = frame.dropna(subset=["epoch", "open", "high", "low", "close"])
    frame["timestamp"] = pd.to_datetime(frame["epoch"], unit="s", utc=True).dt.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    return [
        {
            "epoch": int(row.epoch),
            "timestamp": row.timestamp,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
        }
        for row in frame.itertuples(index=False)
    ]


# ---------------------------------------------------------------------------
# Public async API functions (used by agent_streaming.py and server.py)
# ---------------------------------------------------------------------------
async def get_market_ticks(symbol: str, subscribe: bool = False) -> dict[str, Any]:
    """Fetch the latest Deriv tick for a symbol, optionally sampling a live stream."""
    async with DerivWebSocketClient() as client:
        payload: dict[str, Any] = {"ticks": symbol}
        if subscribe:
            payload["subscribe"] = 1

        first_response = await client.request(payload)
        first_tick = extract_tick(first_response)
        subscription_id = (first_response.get("subscription") or {}).get("id")
        stream_ticks: list[dict[str, Any]] = []

        if subscribe and subscription_id:
            stream_messages = await client.collect_subscription(subscription_id)
            stream_ticks = [extract_tick(message) for message in stream_messages]

        return {
            "symbol": symbol,
            "subscribe": subscribe,
            "subscription_id": subscription_id,
            "tick": first_tick,
            "stream_sample": stream_ticks,
            "stream_sample_limit": SUBSCRIPTION_SAMPLE_SIZE,
            "timeout_seconds": REQUEST_TIMEOUT_SECONDS,
        }


async def get_historical_candles(symbol: str, granularity: int, count: int) -> dict[str, Any]:
    """Fetch Deriv historical candles in normalized OHLCV format."""
    async with DerivWebSocketClient() as client:
        response = await client.request(
            {
                "ticks_history": symbol,
                "adjust_start_time": 1,
                "count": count,
                "end": "latest",
                "granularity": granularity,
                "style": "candles",
            }
        )
        candles = normalize_candles(response)
        return {
            "symbol": symbol,
            "granularity": granularity,
            "requested_count": count,
            "returned_count": len(candles),
            "ohlcv": candles,
        }


# ---------------------------------------------------------------------------
# itertools.count replacement (iterable-based, no side effects at import time)
# ---------------------------------------------------------------------------
def _count(start: int = 0) -> object:  # type: ignore[misc]
    """Simple counter iterator (avoids importing itertools in hot path)."""

    class _Counter:
        def __init__(self, n: int) -> None:
            self.n = n

        def __iter__(self) -> "_Counter":
            return self

        def __next__(self) -> int:
            val = self.n
            self.n += 1
            return val

    return _Counter(start)
