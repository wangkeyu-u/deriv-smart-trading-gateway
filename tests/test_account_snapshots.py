"""Account data must not reduce risk exposure through invalid broker values."""
import asyncio
from dataclasses import replace
from decimal import Decimal

import pytest

from adapters.deriv.models import OpenPosition
from domain.order import OrderStatus as S
from tests.test_execution_faults import approved, broker
from tests.test_trading_service import create, service


POSITION = {'contract_id': 77, 'symbol': 'R_100', 'buy_price': 10}
INVALID_BROKER_DATA = [
    ({'balance': -1}, []),
    ({'balance': float('nan')}, []),
    ({'balance': float('inf')}, []),
    ({}, [POSITION | {'buy_price': -1000}]),
    ({}, [POSITION | {'buy_price': float('nan')}]),
    ({}, [POSITION | {'buy_price': float('inf')}]),
    ({}, [POSITION | {'contract_id': True}]),
    ({}, [POSITION | {'contract_id': '77'}]),
    ({}, [POSITION | {'contract_id': 77.5}]),
    ({}, [POSITION | {'contract_id': 0}]),
    ({}, [POSITION | {'contract_id': -1}]),
    ({}, [POSITION | {'symbol': ''}]),
    ({}, [POSITION | {'symbol': '   '}]),
    ({}, [POSITION | {'symbol': 'R 100'}]),
    ({}, [POSITION | {'symbol': None}]),
    ({}, [POSITION, POSITION]),
    ({}, [POSITION, POSITION | {'buy_price': 0}]),
]


@pytest.mark.parametrize('balance,contracts', INVALID_BROKER_DATA)
def test_invalid_transport_snapshot_blocks_buy_and_records_risk_failure(broker, monkeypatch, balance, contracts):
    application, intent, order = approved(broker)
    original = broker.request
    account_reads = 0

    async def response(self, payload, **kwargs):
        nonlocal account_reads
        if 'balance' in payload:
            account_reads += 1
            if account_reads > 1:
                return {'balance': {'balance': 1000} | balance}
        if 'portfolio' in payload and account_reads > 1:
            return {'portfolio': {'contracts': contracts}}
        return await original(self, payload, **kwargs)

    monkeypatch.setattr(broker, 'request', response)
    result = asyncio.run(application.execute_trade(intent.intent_id))

    assert result.status == S.REJECTED
    assert result.last_error == 'RISK_DATA_UNAVAILABLE'
    assert broker.buys == 0
    with application.repo.db.transaction() as conn:
        assert conn.execute('SELECT code,allowed FROM risk_events WHERE order_id=?', (order.order_id,)).fetchone()[:] == ('RISK_DATA_UNAVAILABLE', 0)
        assert conn.execute('SELECT count(*) FROM order_receipts').fetchone()[0] == 0


@pytest.mark.parametrize('balance,contracts', INVALID_BROKER_DATA)
def test_replacement_adapter_cannot_supply_invalid_account_snapshot(service, monkeypatch, balance, contracts):
    intent = create(service)
    order = asyncio.run(service.validate_trade(intent.intent_id))
    service.approve_trade(intent.intent_id, order.account_id, expected_intent=intent)
    valid = asyncio.run(service.adapter.get_account())
    invalid = replace(valid, balance=Decimal(str(balance.get('balance', 1000))), contracts=tuple(
        OpenPosition(row['contract_id'], row['symbol'], Decimal(str(row['buy_price']))) for row in contracts
    ))
    account_reads = 0

    async def account():
        nonlocal account_reads
        account_reads += 1
        return valid if account_reads == 1 else invalid

    monkeypatch.setattr(service.adapter, 'get_account', account)
    result = asyncio.run(service.execute_trade(intent.intent_id))

    assert result.status == S.REJECTED
    assert result.last_error == 'RISK_DATA_UNAVAILABLE'
    assert service.adapter.buys == 0
