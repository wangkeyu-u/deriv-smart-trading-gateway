"""Read-only reconciliation; never submits or resubmits a broker write."""
import time
import os
import asyncio
from uuid import uuid4
from domain.order import OrderStatus as S


def owner_is_dead(pid):
    if not pid:
        return False
    try:
        os.kill(pid,0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


class Reconciler:
    def __init__(self, repository):
        self.repo = repository

    async def reconcile(self, order_id, adapter):
        lease_token=str(uuid4())
        with self.repo.db.transaction() as conn:
            order = self.repo.get(order_id, conn)
            if order.status != S.UNKNOWN:
                return order
            row = conn.execute('SELECT * FROM reconciliation_jobs WHERE order_id=?', (order_id,)).fetchone()
            if row and row['lease_until'] > time.time() and not owner_is_dead(row['owner_pid']):
                return order
            conn.execute('UPDATE reconciliation_jobs SET lease_until=?,owner_pid=?,lease_token=?,attempts=attempts+1 WHERE order_id=?', (time.time()+60, os.getpid(), lease_token, order_id))
            order = self.repo.transition(order_id, S.RECONCILING, 'reconcile_claimed', conn=conn)
        try:
            result = await adapter.resolve_order(order, self.repo.intent(order.intent_id))
            return self._finish(order_id,lease_token,result=result)
        except asyncio.CancelledError:
            self._finish(order_id,lease_token,error='CancelledError')
            raise
        except Exception as exc:
            return self._finish(order_id,lease_token,error=type(exc).__name__)

    def _finish(self, order_id, lease_token, *, result=None, error=None):
        with self.repo.db.transaction() as conn:
            order=self.repo.get(order_id,conn)
            job=conn.execute('SELECT lease_token FROM reconciliation_jobs WHERE order_id=?',(order_id,)).fetchone()
            # A late response cannot modify an order resolved by a receipt or a newer recovery attempt.
            if order.status != S.RECONCILING or job is None or job[0] != lease_token:
                return order
            # Matching amount/symbol/time alone or an empty portfolio is not definitive evidence.
            if (result is not None and result.verified and result.receipt.get('contract_id')
                    and result.status in {'OPEN','CLOSED','EXPIRED'}
                    and (order.action=='BUY' or result.status=='CLOSED')):
                order = self.repo.acknowledge(order_id, result.receipt,conn)
                terminal = result.status
                if order.status == S.OPEN and terminal in {'CLOSED', 'EXPIRED'}:
                    order = self.repo.transition(order_id, S(terminal), 'broker_settled',conn=conn)
            elif result is not None and result.verified and result.status == 'REJECTED':
                order = self.repo.transition(order_id, S.REJECTED, 'broker_rejection_confirmed',conn=conn)
            else:
                order = self.repo.transition(order_id, S.UNKNOWN,
                    'reconcile_unavailable' if error else 'reconcile_inconclusive',
                    changes={'last_error':error} if error else None,conn=conn)
            if order.status == S.UNKNOWN:
                conn.execute('UPDATE reconciliation_jobs SET due_at=?,lease_until=0 WHERE order_id=?', (time.time()+30, order_id))
            else:
                conn.execute('DELETE FROM reconciliation_jobs WHERE order_id=?', (order_id,))
            return order

    async def recover_incomplete_orders(self, adapter=None, *, now=None):
        now = time.time() if now is None else now
        with self.repo.db.transaction() as conn:
            rows = conn.execute("SELECT order_id,status,lease_until,owner_pid FROM orders WHERE status IN ('SUBMITTING','UNKNOWN','RECONCILING')").fetchall()
            for row in rows:
                if row['status'] == 'SUBMITTING' and (row['lease_until'] <= now or owner_is_dead(row['owner_pid'])):
                    self.repo.transition(row['order_id'], S.UNKNOWN, 'startup_interrupted_submit', conn=conn)
                    conn.execute('UPDATE reconciliation_jobs SET due_at=? WHERE order_id=?',(now,row['order_id']))
                elif row['status'] == 'RECONCILING':
                    job = conn.execute('SELECT lease_until,owner_pid FROM reconciliation_jobs WHERE order_id=?', (row['order_id'],)).fetchone()
                    if job is None or job[0] <= now or owner_is_dead(job[1]):
                        self.repo.transition(row['order_id'], S.UNKNOWN, 'startup_interrupted_reconcile', conn=conn)
                        conn.execute('UPDATE reconciliation_jobs SET due_at=? WHERE order_id=?',(now,row['order_id']))
            jobs = conn.execute('SELECT order_id FROM reconciliation_jobs WHERE due_at<=? AND lease_until<=?', (now,now)).fetchall()
        restored = []
        for job in jobs:
            order = self.repo.get(job[0])
            if adapter is not None:
                if order.account_id != adapter.account_id:
                    continue
                order = await self.reconcile(order.order_id, adapter)
            restored.append(order)
        return restored
