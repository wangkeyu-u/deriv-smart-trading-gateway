from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from server import DerivWebSocketClient


class ConcurrentFakeWebSocket:
    def __init__(self, client: DerivWebSocketClient) -> None:
        self.client = client
        self.requests: list[dict[str, Any]] = []

    async def send(self, raw: str) -> None:
        payload = json.loads(raw)
        self.requests.append(payload)
        if len(self.requests) == 2:
            # Resolve out of order. req_id correlation, not call order, must win.
            second, first = self.requests[1], self.requests[0]
            self.client._pending[second["req_id"]].set_result(
                {"req_id": second["req_id"], "value": second["value"]}
            )
            self.client._pending[first["req_id"]].set_result(
                {"req_id": first["req_id"], "value": first["value"]}
            )


@pytest.mark.asyncio
async def test_concurrent_requests_are_multiplexed_by_req_id() -> None:
    client = DerivWebSocketClient(timeout_seconds=0.2)
    fake = ConcurrentFakeWebSocket(client)
    client._ws = fake  # type: ignore[assignment]
    first, second = await asyncio.gather(
        client._request_once({"value": "first"}),
        client._request_once({"value": "second"}),
    )
    assert first["value"] == "first"
    assert second["value"] == "second"
    assert len({item["req_id"] for item in fake.requests}) == 2
    assert client._pending == {}


@pytest.mark.asyncio
async def test_subscription_queue_applies_drop_oldest_backpressure() -> None:
    client = DerivWebSocketClient(subscription_queue_maxsize=2)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2)
    client._subscriptions["sub-1"] = queue
    for sequence in range(4):
        client._enqueue_subscription("sub-1", {"sequence": sequence})
    assert [queue.get_nowait()["sequence"], queue.get_nowait()["sequence"]] == [2, 3]
    assert client._subscription_dropped["sub-1"] == 2


def test_exponential_backoff_is_capped_and_jittered_deterministically() -> None:
    low = DerivWebSocketClient(random_source=lambda: 0.0)
    middle = DerivWebSocketClient(random_source=lambda: 0.5)
    high = DerivWebSocketClient(random_source=lambda: 1.0)
    assert low._backoff(0) == pytest.approx(0.2)
    assert middle._backoff(0) == pytest.approx(0.25)
    assert high._backoff(0) == pytest.approx(0.3)
    assert middle._backoff(1) == pytest.approx(0.5)
    assert middle._backoff(2) == pytest.approx(1.0)
    assert middle._backoff(99) == pytest.approx(2.0)
    assert high._backoff(99) <= 2.0


@pytest.mark.asyncio
async def test_connection_retries_use_backoff_without_real_sleep(monkeypatch: Any) -> None:
    client = DerivWebSocketClient(max_retries=2, random_source=lambda: 0.5)
    attempts = 0
    delays: list[float] = []

    async def fake_connect() -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("fixture disconnect")

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(client, "_connect_once", fake_connect)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    await client._connect_and_authorize()
    assert attempts == 3
    assert delays == [0.25, 0.5]
