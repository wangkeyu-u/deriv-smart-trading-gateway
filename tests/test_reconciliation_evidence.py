"""Reconciliation needs one attributable transaction, not a similar contract."""
import asyncio

import pytest

from adapters.deriv.models import ContractSnapshot
from domain.order import OrderStatus as S
from tests.test_execution_faults import approved, broker


def uncertain_order(broker, monkeypatch, action):
    service, intent, order = approved(broker, action=action)
    service.repo.claim_submission(order.order_id)
    service.repo.transition(order.order_id, S.UNKNOWN)

    async def contract(contract_id):
        return ContractSnapshot(contract_id, action == 'SELL', False)

    monkeypatch.setattr(service.adapter, 'get_contract', contract)
    return service, order


@pytest.mark.parametrize('action', ['BUY', 'SELL'])
@pytest.mark.parametrize('variant', [
    'wrong_action', 'missing_action', 'multiple_transactions',
    'fractional_contract', 'boolean_contract', 'string_contract', 'zero_contract', 'negative_contract',
    'fractional_transaction', 'boolean_transaction', 'string_transaction', 'zero_transaction', 'negative_transaction',
])
def test_invalid_or_ambiguous_statement_keeps_order_unknown(broker, monkeypatch, action, variant):
    service, order = uncertain_order(broker, monkeypatch, action)
    row = {'contract_id': 42, 'transaction_id': 43, 'action_type': action.lower(),
           'passthrough': {'order_id': order.order_id}}
    changes = {
        'wrong_action': {'action_type': 'sell' if action == 'BUY' else 'buy'},
        'fractional_contract': {'contract_id': 42.9},
        'boolean_contract': {'contract_id': True},
        'string_contract': {'contract_id': '42'},
        'zero_contract': {'contract_id': 0},
        'negative_contract': {'contract_id': -42},
        'fractional_transaction': {'transaction_id': 43.9},
        'boolean_transaction': {'transaction_id': True},
        'string_transaction': {'transaction_id': '43'},
        'zero_transaction': {'transaction_id': 0},
        'negative_transaction': {'transaction_id': -43},
    }
    rows = [row | changes.get(variant, {})]
    if variant == 'missing_action':
        rows[0].pop('action_type')
    if variant == 'multiple_transactions':
        rows.append(row | {'transaction_id': 44})

    async def statement(since):
        return rows

    monkeypatch.setattr(service.adapter, 'get_statement', statement)
    result = asyncio.run(service.reconcile_order(order.order_id))

    assert result.status == S.UNKNOWN
    assert broker.buys == broker.sells == 0
    with service.repo.db.transaction() as conn:
        assert conn.execute('SELECT count(*) FROM order_receipts').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM reconciliation_jobs WHERE order_id=?', (order.order_id,)).fetchone()[0] == 1


def test_sell_closed_by_other_actor_is_not_this_orders_receipt(broker, monkeypatch):
    service, order = uncertain_order(broker, monkeypatch, 'SELL')

    async def statement(since):
        return [{'contract_id': 42, 'transaction_id': 43, 'action_type': 'sell',
                 'passthrough': {'order_id': 'another-order'}}]

    monkeypatch.setattr(service.adapter, 'get_statement', statement)
    assert asyncio.run(service.reconcile_order(order.order_id)).status == S.UNKNOWN
    assert broker.sells == 0


@pytest.mark.parametrize('action', ['BUY', 'SELL'])
@pytest.mark.parametrize('transaction_id', [None, 43])
def test_single_attributable_statement_resolves_even_if_identical_rows_repeat(broker, monkeypatch, action, transaction_id):
    service, order = uncertain_order(broker, monkeypatch, action)
    row = {'contract_id': 42, 'action_type': action.lower(), 'passthrough': {'order_id': order.order_id}}
    if transaction_id is not None:
        row['transaction_id'] = transaction_id

    async def statement(since):
        return [row, row.copy()]

    monkeypatch.setattr(service.adapter, 'get_statement', statement)
    result = asyncio.run(service.reconcile_order(order.order_id))
    assert result.status == (S.OPEN if action == 'BUY' else S.CLOSED)
    assert result.transaction_id == transaction_id
    assert broker.buys == broker.sells == 0
