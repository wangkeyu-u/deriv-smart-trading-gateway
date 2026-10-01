import asyncio
import json
from types import SimpleNamespace

import pytest
from adapters.deriv.client import DerivWebSocketClient, DerivNotSentError, DerivTimeoutError


def test_connection_failure_is_proven_before_send(monkeypatch):
    client=DerivWebSocketClient(max_retries=0)
    async def fail(): raise OSError('offline')
    monkeypatch.setattr(client,'_connect_and_authorize',fail)
    with pytest.raises(DerivNotSentError): asyncio.run(client.request({'buy':'p','price':10},retries=99))


def test_duplicate_websocket_receipt_fulfils_future_once():
    async def check():
        client=DerivWebSocketClient()
        future=asyncio.get_running_loop().create_future()
        client._pending[1]=future
        class Stream:
            def __aiter__(self):
                async def messages():
                    for _ in range(2): yield json.dumps({'req_id':1,'buy':{'contract_id':42}})
                return messages()
        client._ws=Stream()
        await client._receiver_loop()
        assert future.result()['buy']['contract_id']==42
        assert client._pending=={}
    asyncio.run(check())


def test_send_attempt_without_response_is_unknown():
    async def check():
        client=DerivWebSocketClient(timeout_seconds=.01,max_retries=0)
        class Socket:
            async def send(self,payload): pass
            async def close(self): pass
        client._ws=Socket()
        with pytest.raises(DerivTimeoutError) as exc:
            await client.request({'buy':'p','price':10},retries=99)
        assert not isinstance(exc.value,DerivNotSentError)
    asyncio.run(check())
