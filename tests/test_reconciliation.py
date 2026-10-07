import asyncio
import time

from domain.order import OrderStatus as S
from execution.engine import OrderEngine, UnknownOutcomeError
from execution.reconciler import Reconciler
from persistence.database import Database
from persistence.repositories import OrderRepository
from tests.test_order_engine import prepare, repo, Broker
from adapters.deriv.models import ReconciliationResult


class CommittedButTimedOut(Broker):
    account_id = 'VRTC1'
    def __init__(self): super().__init__(UnknownOutcomeError())
    async def resolve_order(self, order, intent):
        return ReconciliationResult(True,'OPEN',{'contract_id':42,'transaction_id':43})


def test_committed_timeout_reconciles_without_second_buy(repo):
    broker = CommittedButTimedOut()
    order = prepare(repo)
    assert asyncio.run(OrderEngine(repo).execute(order.order_id, broker)).status == S.UNKNOWN
    assert asyncio.run(Reconciler(repo).reconcile(order.order_id, broker)).status == S.OPEN
    asyncio.run(OrderEngine(repo).execute(order.order_id, broker))
    assert broker.buys == 1
    assert [e['new_status'] for e in repo.events(order.order_id)][-4:] == ['UNKNOWN','RECONCILING','ACKNOWLEDGED','OPEN']


def test_verified_read_only_reconciliation_can_resolve_without_transaction_identity(repo):
    class ContractIdentified(CommittedButTimedOut):
        async def resolve_order(self, order, intent):
            return ReconciliationResult(True, 'OPEN', {'contract_id': 42})

    order = prepare(repo)
    adapter = ContractIdentified()
    assert asyncio.run(OrderEngine(repo).execute(order.order_id, adapter)).status == S.UNKNOWN
    resolved = asyncio.run(Reconciler(repo).reconcile(order.order_id, adapter))
    assert resolved.status == S.OPEN
    assert resolved.contract_id == 42
    assert resolved.transaction_id is None
    assert adapter.buys == 1


def test_restart_after_submitting_recovers_only_by_reads(repo):
    order = prepare(repo)
    repo.claim_submission(order.order_id)
    restarted = OrderRepository(Database(repo.db.path))
    broker = CommittedButTimedOut()
    result = asyncio.run(Reconciler(restarted).recover_incomplete_orders(broker, now=time.time()+120))
    assert result[0].status == S.OPEN
    assert broker.buys == 0


def test_active_submit_lease_is_not_stolen_by_another_process(repo):
    order = prepare(repo)
    repo.claim_submission(order.order_id)
    assert asyncio.run(Reconciler(repo).recover_incomplete_orders()) == []
    assert repo.get(order.order_id).status == S.SUBMITTING


def test_empty_portfolio_and_heuristic_match_leave_unknown(repo):
    class Inconclusive(CommittedButTimedOut):
        async def resolve_order(self, order, intent):
            return ReconciliationResult(False,'OPEN',{'contract_id':42})
    order=prepare(repo)
    broker=Inconclusive()
    asyncio.run(OrderEngine(repo).execute(order.order_id,broker))
    assert asyncio.run(Reconciler(repo).reconcile(order.order_id,broker)).status == S.UNKNOWN
    assert broker.buys == 1


def test_actual_process_exit_after_claim_recovers_without_waiting_for_lease(repo):
    import subprocess
    import sys
    from pathlib import Path
    order=prepare(repo)
    code="from persistence.database import Database; from persistence.repositories import OrderRepository; import sys; repo=OrderRepository(Database(sys.argv[1])); repo.claim_submission(sys.argv[2])"
    result=subprocess.run([sys.executable,'-c',code,str(repo.db.path),order.order_id],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    broker=CommittedButTimedOut()
    recovered=asyncio.run(Reconciler(repo).recover_incomplete_orders(broker))
    assert recovered[0].status==S.OPEN
    assert broker.buys==0
