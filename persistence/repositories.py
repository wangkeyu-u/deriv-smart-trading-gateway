from __future__ import annotations

import hashlib
import json
import time
import os
from datetime import timedelta

from domain.order import Order, OrderEvent, OrderStatus as S
from domain.trade import TradeIntent, utc_now

TRANSITIONS = {
    S.CREATED: {S.VALIDATED, S.REJECTED, S.CANCELLED},
    S.VALIDATED: {S.APPROVAL_REQUIRED, S.REJECTED, S.CANCELLED},
    S.APPROVAL_REQUIRED: {S.APPROVED, S.REJECTED, S.CANCELLED},
    S.APPROVED: {S.SUBMITTING, S.REJECTED, S.CANCELLED},
    S.SUBMITTING: {S.ACKNOWLEDGED, S.REJECTED, S.UNKNOWN},
    S.ACKNOWLEDGED: {S.OPEN, S.CLOSED, S.EXPIRED, S.UNKNOWN},
    S.OPEN: {S.CLOSED, S.EXPIRED},
    S.UNKNOWN: {S.RECONCILING},
    S.RECONCILING: {S.ACKNOWLEDGED, S.OPEN, S.CLOSED, S.EXPIRED, S.REJECTED, S.UNKNOWN},
}


def fingerprint(intent: TradeIntent, account_id: str) -> str:
    values = intent.model_dump(mode='json', exclude={'created_at', 'source', 'request_id', 'correlation_id'})
    values['amount'] = format(intent.amount.normalize(), 'f')
    values['account_id'] = account_id
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


class OrderRepository:
    def __init__(self, database):
        self.db = database

    def save_intent(self, intent):
        with self.db.transaction() as conn:
            old = conn.execute('SELECT raw_payload FROM trade_intents WHERE intent_id=?', (intent.intent_id,)).fetchone()
            if old:
                existing = TradeIntent.model_validate_json(old[0])
                if fingerprint(existing, '') != fingerprint(intent, ''):
                    raise ValueError('intent_id is already bound to different parameters')
                return existing
            conn.execute('INSERT INTO trade_intents VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                         (intent.intent_id, intent.source, intent.action, intent.symbol, intent.direction,
                          str(intent.amount), intent.duration, intent.duration_unit, intent.account_mode,
                          intent.created_at.isoformat(), intent.model_dump_json()))
        return intent

    def intent(self, intent_id):
        with self.db.transaction() as conn:
            row = conn.execute('SELECT raw_payload FROM trade_intents WHERE intent_id=?', (intent_id,)).fetchone()
        if not row:
            raise KeyError('Unknown intent_id')
        return TradeIntent.model_validate_json(row[0])

    def create_order(self, intent, account_id, request_id='', correlation_id=''):
        self.save_intent(intent)
        key = fingerprint(intent, account_id)
        with self.db.transaction() as conn:
            old = conn.execute('SELECT data_json FROM orders WHERE intent_id=?', (intent.intent_id,)).fetchone()
            if old:
                order = Order.model_validate_json(old[0])
                if order.idempotency_key != key:
                    raise ValueError('Intent account or parameters changed')
                return order
            order = Order(intent_id=intent.intent_id, idempotency_key=key, account_id=account_id,
                          action=intent.action, symbol=intent.symbol, direction=intent.direction,
                          amount=intent.amount, contract_id=intent.contract_id,
                          request_id=request_id, correlation_id=correlation_id or intent.correlation_id or request_id)
            conn.execute('INSERT INTO orders(order_id,intent_id,idempotency_key,account_id,status,symbol,direction,amount,contract_id,created_at,updated_at,data_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                         (order.order_id, order.intent_id, key, account_id, order.status, order.symbol,
                          order.direction, str(order.amount), order.contract_id, order.created_at.isoformat(),
                          order.updated_at.isoformat(), order.model_dump_json()))
            self._event(conn, order, None, 'created', {})
        return order

    def get(self, order_id, conn=None):
        if conn is None:
            with self.db.transaction() as connection:
                return self.get(order_id, connection)
        row = conn.execute('SELECT data_json FROM orders WHERE order_id=?', (order_id,)).fetchone()
        if row is None:
            raise KeyError('Unknown order_id')
        return Order.model_validate_json(row[0])

    def by_intent(self, intent_id):
        with self.db.transaction() as conn:
            row = conn.execute('SELECT order_id FROM orders WHERE intent_id=?', (intent_id,)).fetchone()
            return self.get(row[0], conn) if row else None

    def list(self, account_id=None, statuses=None, conn=None):
        if conn is None:
            with self.db.transaction() as connection:
                return self.list(account_id, statuses, connection)
        result = [Order.model_validate_json(row[0]) for row in conn.execute('SELECT data_json FROM orders')]
        return [order for order in result if (account_id is None or order.account_id == account_id) and (statuses is None or order.status in statuses)]

    def _event(self, conn, order, previous, kind, payload):
        event = OrderEvent(order_id=order.order_id, previous_status=previous, new_status=order.status,
                           event_type=kind, payload={'request_id': order.request_id, 'intent_id': order.intent_id,
                                                     'correlation_id': order.correlation_id, **payload})
        conn.execute('INSERT INTO order_events VALUES(?,?,?,?,?,?,?)',
                     (event.event_id, order.order_id, previous, order.status, kind, event.timestamp.isoformat(), json.dumps(event.payload)))

    def transition(self, order_id, status, kind='transition', *, expected=None, changes=None, conn=None):
        if conn is None:
            with self.db.transaction() as connection:
                return self.transition(order_id, status, kind, expected=expected, changes=changes, conn=connection)
        old = self.get(order_id, conn)
        if old.status == status or (expected is not None and old.status != expected):
            return old
        if status not in TRANSITIONS.get(old.status, set()):
            # Late/duplicate acknowledgements cannot move OPEN or terminal states backwards.
            if status in {S.ACKNOWLEDGED, S.OPEN} and old.status in {S.OPEN, S.CLOSED, S.EXPIRED}:
                return old
            raise ValueError(f'Invalid order transition: {old.status} -> {status}')
        order = old.model_copy(update={'status': status, 'updated_at': utc_now(), **(changes or {})})
        conn.execute('UPDATE orders SET status=?,contract_id=?,transaction_id=?,updated_at=?,last_error=?,data_json=? WHERE order_id=?',
                     (status, order.contract_id, order.transaction_id, order.updated_at.isoformat(), order.last_error, order.model_dump_json(), order_id))
        self._event(conn, order, old.status, kind, {})
        if status == S.SUBMITTING:
            conn.execute('UPDATE orders SET lease_until=?,owner_pid=? WHERE order_id=?', (time.time() + 60, os.getpid(), order_id))
        if status == S.UNKNOWN:
            conn.execute('INSERT INTO reconciliation_jobs(order_id,due_at) VALUES(?,?) ON CONFLICT(order_id) DO UPDATE SET due_at=excluded.due_at,lease_until=0,owner_pid=NULL', (order_id, time.time()))
        return order

    def claim_submission(self, order_id, risk_check=None):
        with self.db.transaction() as conn:
            old = self.get(order_id, conn)
            if old.status != S.APPROVED:
                return old, False
            if risk_check is not None:
                allowed = risk_check(conn, old)
                if not allowed:
                    return self.transition(order_id, S.REJECTED, 'risk_rejected', conn=conn), False
            return self.transition(order_id, S.SUBMITTING, 'submit_claimed', expected=S.APPROVED,
                                   changes={'submitted_at': utc_now()}, conn=conn), True

    def acknowledge(self, order_id, receipt):
        with self.db.transaction() as conn:
            old = self.get(order_id, conn)
            if old.status in {S.OPEN, S.CLOSED, S.EXPIRED, S.REJECTED, S.CANCELLED}:
                return old
            for row in conn.execute('SELECT order_id,receipt_json FROM order_receipts WHERE account_id=?',(old.account_id,)):
                other=json.loads(row['receipt_json'])
                if row['order_id']!=order_id and old.action=='BUY' and other.get('contract_id')==receipt.get('contract_id'):
                    return self.transition(order_id,S.UNKNOWN,'conflicting_broker_identity',changes={'last_error':'BROKER_IDENTITY_CONFLICT'},conn=conn)
            if old.status==S.UNKNOWN:
                old=self.transition(order_id,S.RECONCILING,'late_receipt_resolution',conn=conn)
            conn.execute('INSERT OR IGNORE INTO order_receipts VALUES(?,?,?,?)',
                         (order_id, old.account_id, receipt.get('transaction_id'), json.dumps(receipt)))
            order = self.transition(order_id, S.ACKNOWLEDGED, 'broker_ack', changes={
                'receipt': receipt, 'contract_id': receipt['contract_id'],
                'transaction_id': receipt.get('transaction_id'), 'last_error': None}, conn=conn)
            return self.transition(order_id, S.CLOSED if order.action == 'SELL' else S.OPEN, 'broker_effect_confirmed', conn=conn)

    def events(self, order_id):
        with self.db.transaction() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM order_events WHERE order_id=? ORDER BY rowid', (order_id,))]
