import asyncio
from decimal import Decimal
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from domain.trade import TradeIntent
from domain.order import OrderStatus as S
from execution.engine import OrderEngine, NotSentError, UnknownOutcomeError
from persistence.database import Database
from persistence.repositories import OrderRepository


@pytest.fixture
def repo(tmp_path):
    return OrderRepository(Database(tmp_path/'orders.sqlite3'))


def prepare(repo, intent_id='intent-one'):
    intent = TradeIntent(intent_id=intent_id, action='BUY', symbol='R_100', direction='CALL',
                         amount=Decimal('10'), duration=5, duration_unit='t', account_mode='demo', source='streamlit')
    order = repo.create_order(intent, 'VRTC1')
    for status in (S.VALIDATED, S.APPROVAL_REQUIRED, S.APPROVED):
        order = repo.transition(order.order_id, status)
    return order


class Broker:
    def __init__(self, failure=None): self.buys=0; self.failure=failure
    async def place_order(self, intent, order):
        self.buys += 1
        if self.failure: raise self.failure
        return {'contract_id': 42, 'transaction_id': 43}


def test_duplicate_and_concurrent_requests_buy_once(repo):
    order = prepare(repo)
    broker = Broker()
    def execute(): return asyncio.run(OrderEngine(repo).execute(order.order_id, broker))
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _: execute(), range(2)))
    assert execute().status == S.OPEN
    assert broker.buys == 1
    assert len(repo.list()) == 1
    with repo.db.transaction() as conn:
        assert conn.execute('SELECT count(*) FROM order_receipts').fetchone()[0] == 1
    assert repo.acknowledge(order.order_id, {'contract_id':42,'transaction_id':43}).status == S.OPEN
    assert repo.transition(order.order_id, S.ACKNOWLEDGED).status == S.OPEN


@pytest.mark.parametrize('failure,status', [(NotSentError(), S.REJECTED), (UnknownOutcomeError(), S.UNKNOWN)])
def test_before_send_and_after_send_are_distinct(repo, failure, status):
    order = prepare(repo)
    broker = Broker(failure)
    assert asyncio.run(OrderEngine(repo).execute(order.order_id, broker)).status == status
    asyncio.run(OrderEngine(repo).execute(order.order_id, broker))
    assert broker.buys == 1


def test_migration_preserves_existing_history_and_events_are_append_only(tmp_path):
    path = tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE advisor_runs(id INTEGER PRIMARY KEY, result_json TEXT)')
        conn.execute("INSERT INTO advisor_runs VALUES(1, 'original')")
    repo = OrderRepository(Database(path))
    Database(path)
    order = prepare(repo)
    with repo.db.transaction() as conn:
        assert conn.execute('SELECT result_json FROM advisor_runs').fetchone()[0] == 'original'
        with pytest.raises(sqlite3.IntegrityError, match='append only'):
            conn.execute('DELETE FROM order_events')
    assert [event['new_status'] for event in repo.events(order.order_id)] == ['CREATED','VALIDATED','APPROVAL_REQUIRED','APPROVED']


def test_same_intent_with_changed_amount_cannot_be_reused(repo):
    order = prepare(repo)
    changed = repo.intent(order.intent_id).model_copy(update={'amount': Decimal('100')})
    with pytest.raises(ValueError, match='different parameters'):
        repo.create_order(changed, 'VRTC1')


def test_equivalent_decimal_representation_preserves_idempotency(repo):
    order=prepare(repo)
    equivalent=repo.intent(order.intent_id).model_copy(update={'amount':Decimal('10.00')})
    assert repo.create_order(equivalent,'VRTC1').order_id==order.order_id
