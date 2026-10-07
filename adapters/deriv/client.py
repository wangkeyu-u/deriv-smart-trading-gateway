from __future__ import annotations
import asyncio
import json
import os
import ssl
from datetime import datetime, timezone
from itertools import count
from typing import Any
import certifi
import pandas as pd
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException
APP_ID=os.getenv('DERIV_APP_ID','1089')
DERIV_WS_URL_TEMPLATE=os.getenv('DERIV_WS_URL_TEMPLATE','wss://ws.derivws.com/websockets/v3?app_id={app_id}')
REQUEST_TIMEOUT_SECONDS=5.
SUBSCRIPTION_SAMPLE_SIZE=5

class GatewayError(Exception):
    """Base error for gateway failures."""


class DerivAPIError(GatewayError):
    """Deriv returned an application-level error payload."""


class DerivTimeoutError(GatewayError):
    """Deriv did not return the expected response in time."""


class DerivNotSentError(DerivTimeoutError):
    """No write reached the send operation."""


def deriv_error_message(response: dict[str, Any]) -> str:
    error = response.get("error") or {}
    code = error.get("code", "DerivAPIError")
    message = error.get("message", "Deriv returned an error response")
    return f"{code}: {message}"


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
        self._req_ids = count(1)
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._subscriptions: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._request_lock = asyncio.Lock()
        self._authorized = False
        self.authorization: dict[str, Any] | None = None

    async def __aenter__(self) -> "DerivWebSocketClient":
        try:
            await self._connect_and_authorize()
        except BaseException:
            await self.close()
            raise
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
                if subscription_id in self._subscriptions:
                    await self._subscriptions[subscription_id].put(message)
        except asyncio.CancelledError:
            raise
        except ConnectionClosed as exc:
            self._fail_pending(exc)
        except Exception as exc:
            self._fail_pending(exc)

    def _fail_pending(self, exc: BaseException) -> None:
        for req_id, future in list(self._pending.items()):
            if not future.done():
                future.set_exception(exc)
            self._pending.pop(req_id, None)

    async def request(
        self,
        payload: dict[str, Any],
        *,
        retries: int | None = None,
        allow_deriv_error: bool = False,
    ) -> dict[str, Any]:
        is_write = any(key in payload for key in ("buy", "sell"))
        attempts = 0 if is_write else self.max_retries if retries is None else retries
        for attempt in range(attempts + 1):
            try:
                if self._ws is None:
                    try:
                        await self._connect_and_authorize()
                    except Exception as exc:
                        if is_write:
                            raise DerivNotSentError("Connection failed before send") from exc
                        raise
                response = await self._request_once(payload)
                if response.get("error") and not allow_deriv_error:
                    raise DerivAPIError(deriv_error_message(response))
                return response
            except (DerivAPIError, DerivNotSentError):
                raise
            except (ConnectionClosed, OSError, TimeoutError, WebSocketException, DerivTimeoutError):
                await self.close()
                if attempt >= attempts:
                    raise DerivTimeoutError("Deriv request timed out or the WebSocket closed")
                await asyncio.sleep(self._backoff(attempt))

        raise DerivTimeoutError("Deriv request failed after retries")

    async def _request_once(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._ws is None:
            raise DerivNotSentError("WebSocket is not connected")

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


def summarize_portfolio(portfolio_response: dict[str, Any]) -> dict[str, Any]:
    contracts = (portfolio_response.get("portfolio") or {}).get("contracts") or []
    total_buy_price = 0.0
    total_payout = 0.0
    contract_rows: list[dict[str, Any]] = []

    for contract in contracts:
        buy_price = float(contract.get("buy_price") or 0)
        payout = float(contract.get("payout") or 0)
        total_buy_price += buy_price
        total_payout += payout
        contract_rows.append(
            {
                "contract_id": contract.get("contract_id"),
                "symbol": contract.get("symbol"),
                "contract_type": contract.get("contract_type"),
                "buy_price": buy_price,
                "payout": payout,
                "expiry_time": contract.get("expiry_time"),
                "transaction_id": contract.get("transaction_id"),
            }
        )

    return {
        "open_contract_count": len(contracts),
        "total_open_buy_price": total_buy_price,
        "total_potential_payout": total_payout,
        "contracts": contract_rows,
    }
