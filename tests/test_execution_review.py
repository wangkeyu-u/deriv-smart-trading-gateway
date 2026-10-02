"""Regression cases found while reviewing the durable execution boundary."""
import asyncio
import sqlite3
from decimal import Decimal

import pytest

from adapters.deriv.models import ContractSnapshot, Proposal, ReconciliationResult
from domain.order import OrderStatus as S
from execution.engine import OrderEngine, UnknownOutcomeError
from execution.reconciler import Reconciler
from tests.test_execution_faults import approved, broker
from tests.test_order_engine import Broker, prepare, repo
from tests.test_trading_service import create, service


def test_existing_approval_does_not_authorize_changed_confirmation(service):
    intent = create(service)
    order = asyncio.run(service.validate_trade(intent.intent_id))
    service.approve_trade(intent.intent_id, order.account_id, expected_intent=intent)
    changed = intent.model_copy(update={'amount': Decimal('100')})
    with pytest.raises(ValueError, match='parameters'):
        asyncio.run(service.confirm_and_execute(changed))
    assert service.adapter.buys == 0
    assert service.repo.get(order.order_id).status == S.APPROVED


def test_interrupted_validation_resumes_to_approval_required(service):
    intent = create(service)
    order = service.repo.create_order(intent, service.adapter.account_id)
    service.repo.transition(order.order_id, S.VALIDATED)
    assert asyncio.run(service.validate_trade(intent.intent_id)).status == S.APPROVAL_REQUIRED


def test_duplicate_submission_still_authenticates_account(broker):
    service, intent, order = approved(broker)
    assert asyncio.run(service.execute_trade(intent.intent_id)).status == S.OPEN
    broker.loginid = 'VRTC_OTHER'
    from services.trading_service import trading_application
    other = trading_application('different-token')
    with pytest.raises(ValueError, match='account'):
        asyncio.run(other.execute_trade(intent.intent_id))
    assert broker.buys == 1


@pytest.mark.parametrize('sell_result', [None, {}, {'contract_id': 999, 'transaction_id': 44, 'sold_for': 9}])
def test_invalid_sell_ack_is_unknown_and_never_retried(broker, monkeypatch, sell_result):
    service, intent, order = approved(broker, action='SELL')
    original = broker.request
    async def response(self, payload, **kwargs):
        if 'sell' in payload:
            type(self).sells += 1
            return {'sell': sell_result}
        return await original(self, payload, **kwargs)
    monkeypatch.setattr(broker, 'request', response)
    assert asyncio.run(service.close_trade(intent.intent_id)).status == S.UNKNOWN
    assert asyncio.run(service.close_trade(intent.intent_id)).status == S.UNKNOWN
    assert broker.sells == 1
    with service.repo.db.transaction() as conn:
        assert conn.execute('SELECT count(*) FROM order_receipts').fetchone()[0] == 0


def test_transaction_identity_cannot_silently_skip_receipt(repo):
    first = prepare(repo, 'first')
    second = prepare(repo, 'second')
    repo.claim_submission(first.order_id)
    repo.claim_submission(second.order_id)
    assert repo.acknowledge(first.order_id, {'contract_id': 42, 'transaction_id': 43}).status == S.OPEN
    result = repo.acknowledge(second.order_id, {'contract_id': 999, 'transaction_id': 43})
    assert result.status == S.UNKNOWN
    assert result.last_error == 'BROKER_IDENTITY_CONFLICT'
    with repo.db.transaction() as conn:
        assert conn.execute('SELECT count(*) FROM order_receipts').fetchone()[0] == 1


def test_receipt_storage_failure_after_send_becomes_unknown(repo, monkeypatch):
    order = prepare(repo)
    def failed_storage(*args):
        raise sqlite3.OperationalError('Injected storage failure after broker response')
    monkeypatch.setattr(repo, 'acknowledge', failed_storage)
    adapter = Broker()
    result = asyncio.run(OrderEngine(repo).execute(order.order_id, adapter))
    assert result.status == S.UNKNOWN
    assert adapter.buys == 1


def test_expired_contract_is_not_proof_of_unknown_sell(broker):
    service, intent, order = approved(broker, action='SELL')
    service.repo.claim_submission(order.order_id)
    service.repo.transition(order.order_id, S.UNKNOWN)
    async def expired(cid):
        return ContractSnapshot(cid, True, True)
    service.adapter.get_contract = expired
    assert asyncio.run(service.reconcile_order(order.order_id)).status == S.UNKNOWN
    assert broker.sells == 0


def test_reconciled_sell_updates_parent_buy(broker):
    buy_service, buy_intent, buy = approved(broker)
    asyncio.run(buy_service.execute_trade(buy_intent.intent_id))
    service, intent, order = approved(broker, action='SELL')
    service.repo.claim_submission(order.order_id)
    service.repo.transition(order.order_id, S.UNKNOWN)
    async def resolved(order, intent):
        return ReconciliationResult(True, 'CLOSED', {'contract_id': 42, 'transaction_id': 44})
    service.adapter.resolve_order = resolved
    assert asyncio.run(service.reconcile_order(order.order_id)).status == S.CLOSED
    assert service.repo.get(buy.order_id).status == S.CLOSED


def test_sell_contract_binding_cannot_change_confirmed_target(broker):
    service, intent, order = approved(broker, action='SELL')
    service.repo.claim_submission(order.order_id)
    service.repo.transition(order.order_id, S.UNKNOWN)
    async def contract(cid):
        return ContractSnapshot(cid, True, False)
    service.adapter.get_contract = contract
    with pytest.raises(ValueError, match='contract'):
        asyncio.run(service.bind_reconciliation_contract(order.order_id, 999))
    assert service.repo.get(order.order_id).contract_id == 42


def test_reconciliation_cancellation_releases_lease(repo):
    order = prepare(repo)
    repo.claim_submission(order.order_id)
    repo.transition(order.order_id, S.UNKNOWN)
    class Cancelled:
        async def resolve_order(self, order, intent):
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(Reconciler(repo).reconcile(order.order_id, Cancelled()))
    assert repo.get(order.order_id).status == S.UNKNOWN
    with repo.db.transaction() as conn:
        assert conn.execute('SELECT lease_until FROM reconciliation_jobs').fetchone()[0] == 0


def test_late_inconclusive_read_cannot_overwrite_acknowledged_order(repo):
    order = prepare(repo)
    repo.claim_submission(order.order_id)
    repo.transition(order.order_id, S.UNKNOWN)
    class LateRead:
        async def resolve_order(self, order, intent):
            repo.acknowledge(order.order_id, {'contract_id': 42, 'transaction_id': 43})
            return ReconciliationResult(False)
    assert asyncio.run(Reconciler(repo).reconcile(order.order_id, LateRead())).status == S.OPEN
    with repo.db.transaction() as conn:
        assert conn.execute('SELECT count(*) FROM reconciliation_jobs').fetchone()[0] == 0


def test_proposal_limit_is_enforced_at_service_boundary(service):
    intent = create(service)
    order = asyncio.run(service.validate_trade(intent.intent_id))
    service.approve_trade(intent.intent_id, order.account_id, expected_intent=intent)
    async def excessive(intent):
        return Proposal('too-expensive', Decimal('100'))
    service.adapter.get_proposal = excessive
    with pytest.raises(ValueError, match='proposal'):
        asyncio.run(service.execute_trade(intent.intent_id))
    assert service.adapter.buys == 0


def test_concurrent_validations_do_not_regress_approval(service):
    from concurrent.futures import ThreadPoolExecutor
    intent = create(service)
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: asyncio.run(service.validate_trade(intent.intent_id)), range(4)))
    assert {order.status for order in results} == {S.APPROVAL_REQUIRED}
    assert [row['new_status'] for row in service.repo.events(results[0].order_id)] == ['CREATED', 'VALIDATED', 'APPROVAL_REQUIRED']


def test_old_reconciliation_attempt_cannot_finish_new_lease(repo):
    order = prepare(repo)
    repo.claim_submission(order.order_id)
    repo.transition(order.order_id, S.UNKNOWN)
    reconciler = Reconciler(repo)
    class Superseded:
        async def resolve_order(self, order, intent):
            repo.transition(order.order_id, S.UNKNOWN)
            repo.transition(order.order_id, S.RECONCILING)
            with repo.db.transaction() as conn:
                conn.execute('UPDATE reconciliation_jobs SET lease_token=? WHERE order_id=?', ('new-owner', order.order_id))
            return ReconciliationResult(True, 'OPEN', {'contract_id': 42})
    result = asyncio.run(reconciler.reconcile(order.order_id, Superseded()))
    assert result.status == S.RECONCILING
    with repo.db.transaction() as conn:
        assert conn.execute('SELECT lease_token FROM reconciliation_jobs').fetchone()[0] == 'new-owner'
        assert conn.execute('SELECT count(*) FROM order_receipts').fetchone()[0] == 0


def test_distinct_sell_intents_cannot_close_same_contract_twice(broker):
    from concurrent.futures import ThreadPoolExecutor
    first, first_intent, _ = approved(broker, action='SELL')
    second, second_intent, _ = approved(broker, action='SELL')
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda pair: asyncio.run(pair[0].close_trade(pair[1].intent_id)),
                               [(first, first_intent), (second, second_intent)]))
    assert {result.status for result in results} == {S.CLOSED, S.REJECTED}
    assert broker.sells == 1
    rejected = next(result for result in results if result.status == S.REJECTED)
    assert rejected.last_error == 'CONTRACT_CLOSE_IN_PROGRESS'


@pytest.mark.parametrize('flags', [{'is_sold': '0', 'is_expired': '0'}, {'is_sold': 1}])
def test_malformed_contract_flags_do_not_confirm_settlement(broker, monkeypatch, flags):
    service, intent, _ = approved(broker)
    order = asyncio.run(service.execute_trade(intent.intent_id))
    original = broker.request
    async def response(self, payload, **kwargs):
        if 'proposal_open_contract' in payload:
            return {'proposal_open_contract': {'contract_id': 42, **flags}}
        return await original(self, payload, **kwargs)
    monkeypatch.setattr(broker, 'request', response)
    with pytest.raises(ValueError, match='contract state'):
        asyncio.run(service.refresh_order(order.order_id))
    assert service.repo.get(order.order_id).status == S.OPEN


def test_authorization_failure_closes_open_connection(monkeypatch):
    from adapters.deriv.client import DerivWebSocketClient, DerivAPIError
    async def run():
        client = DerivWebSocketClient(api_token='fake', max_retries=0)
        closed = []
        class Socket:
            async def close(self):
                closed.append(True)
        async def fail():
            client._ws = Socket()
            raise DerivAPIError('Authorization rejected')
        monkeypatch.setattr(client, '_connect_and_authorize', fail)
        with pytest.raises(DerivAPIError):
            async with client:
                pytest.fail('Authorization failure must not enter the block')
        assert closed == [True]
        assert client._ws is None
    asyncio.run(run())


def test_profit_history_reads_past_first_page_to_determine_loss_streak(broker, monkeypatch):
    from datetime import datetime, timezone
    service, _, _ = approved(broker)
    midnight = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    first = [dict(contract_id=i+1, buy_price=10, sell_price=0, sell_time=midnight-i-1) for i in range(100)]
    winner = dict(contract_id=101, buy_price=10, sell_price=11, sell_time=midnight-101)
    offsets = []
    original = broker.request
    async def response(self, payload, **kwargs):
        if 'profit_table' in payload:
            offsets.append(payload['offset'])
            return {'profit_table': {'transactions': first if payload['offset'] == 0 else [winner]}}
        return await original(self, payload, **kwargs)
    monkeypatch.setattr(broker, 'request', response)
    rows = asyncio.run(service.adapter.get_closed_contracts())
    assert len(rows) == 101 and offsets == [0, 100]


def test_duplicate_profit_records_are_not_counted_twice(broker, monkeypatch):
    service, _, _ = approved(broker)
    row = dict(contract_id=42, buy_price=10, sell_price=20, sell_time=1)
    original = broker.request
    async def response(self, payload, **kwargs):
        if 'profit_table' in payload:
            return {'profit_table': {'transactions': [row, row]}}
        return await original(self, payload, **kwargs)
    monkeypatch.setattr(broker, 'request', response)
    assert len(asyncio.run(service.adapter.get_closed_contracts())) == 1


def test_late_network_failure_does_not_undo_committed_receipt(repo):
    order = prepare(repo)
    class LateFailure:
        async def place_order(self, intent, order):
            repo.acknowledge(order.order_id, {'contract_id': 42, 'transaction_id': 43})
            raise UnknownOutcomeError('Late disconnect')
    assert asyncio.run(OrderEngine(repo).execute(order.order_id, LateFailure())).status == S.OPEN
    with repo.db.transaction() as conn:
        assert conn.execute('SELECT count(*) FROM reconciliation_jobs').fetchone()[0] == 0


def test_refresh_cannot_regress_concurrent_close(broker):
    service, intent, _ = approved(broker)
    order = asyncio.run(service.execute_trade(intent.intent_id))
    async def concurrent_close(cid):
        service.repo.transition(order.order_id, S.CLOSED)
        return ContractSnapshot(cid, True, True)
    service.adapter.get_contract = concurrent_close
    assert asyncio.run(service.refresh_order(order.order_id)).status == S.CLOSED


@pytest.mark.parametrize('invalid', [{'sell_time': float('nan')}, {'buy_price': -10}, {'sell_price': -10}])
def test_invalid_profit_numbers_are_rejected_before_risk_calculation(broker, monkeypatch, invalid):
    service, _, _ = approved(broker)
    row = dict(contract_id=42, buy_price=10, sell_price=0, sell_time=1) | invalid
    original = broker.request
    async def response(self, payload, **kwargs):
        if 'profit_table' in payload:
            return {'profit_table': {'transactions': [row]}}
        return await original(self, payload, **kwargs)
    monkeypatch.setattr(broker, 'request', response)
    with pytest.raises(ValueError, match='profit record'):
        asyncio.run(service.adapter.get_closed_contracts())


def test_expired_sell_can_resolve_with_matching_sell_statement(broker):
    service, intent, order = approved(broker, action='SELL')
    service.repo.claim_submission(order.order_id)
    service.repo.transition(order.order_id, S.UNKNOWN)
    async def contract(cid):
        return ContractSnapshot(cid, True, True)
    async def statement(since):
        return [{'contract_id': 42, 'transaction_id': 44, 'action_type': 'sell',
                 'passthrough': {'order_id': order.order_id}}]
    service.adapter.get_contract = contract
    service.adapter.get_statement = statement
    result = asyncio.run(service.reconcile_order(order.order_id))
    assert result.status == S.CLOSED and result.transaction_id == 44
    assert broker.sells == 0
