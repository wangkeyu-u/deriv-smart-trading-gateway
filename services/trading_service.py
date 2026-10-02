"""Shared deterministic application for UI, Manager and MCP."""
from datetime import timedelta, datetime, timezone
from decimal import Decimal
import time
import json
from uuid import uuid4
from domain.risk import RiskSnapshot, RiskResult, TradingState
from risk.engine import RiskEngine
from risk.policy import RiskPolicy
import os

from domain.approval import Approval
from domain.order import OrderStatus as S
from domain.trade import TradeIntent, TradeSource, utc_now
from execution.engine import OrderEngine
from execution.reconciler import Reconciler
from persistence.database import Database
from persistence.repositories import OrderRepository, fingerprint
from services.context import ExecutionContext


class AccountValidationError(ValueError):
    def __init__(self, code):
        self.code=code
        super().__init__(code)


class TradingService:
    def __init__(self, database, adapter, context=None):
        self.repo=OrderRepository(database)
        self.adapter=adapter
        self.context=context or ExecutionContext('streamlit')
        self.engine=OrderEngine(self.repo)
        self.reconciler=Reconciler(self.repo)
        self.risk_engine=RiskEngine()
        self.policy=RiskPolicy.configured()

    def create_trade_intent(self, intent: TradeIntent):
        if not intent.request_id:
            intent=intent.model_copy(update={'request_id':self.context.request_id,'correlation_id':self.context.request_id})
        return self.repo.save_intent(intent)

    async def validate_trade(self, intent_id):
        intent=self.repo.intent(intent_id)
        self.context.require_time()
        try:
            account=await self.adapter.get_account()
        except Exception as exc:
            raise AccountValidationError('account_authorization_unverified') from exc
        if account.mode != intent.account_mode:
            raise AccountValidationError('live_account_blocked' if account.mode=='live' else 'account_mode_mismatch')
        order=self.repo.create_order(intent,account.account_id,self.context.request_id)
        with self.repo.db.transaction() as conn:
            order=self.repo.get(order.order_id,conn)
            if order.status == S.CREATED:
                order=self.repo.transition(order.order_id,S.VALIDATED,'validated',conn=conn)
            if order.status == S.VALIDATED:
                order=self.repo.transition(order.order_id,S.APPROVAL_REQUIRED,'approval_required',conn=conn)
        return order

    def approve_trade(self, intent_id, account_id, *, expected_intent, approved_by='local-user'):
        intent=self.repo.intent(intent_id)
        if fingerprint(intent,account_id) != fingerprint(expected_intent,account_id):
            raise ValueError('Approval parameters do not match the immutable intent')
        order=self.repo.by_intent(intent_id)
        if order is None or order.account_id != account_id:
            raise ValueError('Approval account mismatch')
        approval=Approval(intent_id=intent_id,account_id=account_id,symbol=intent.symbol,direction=intent.direction,
            amount=intent.amount,duration=intent.duration,duration_unit=intent.duration_unit,account_mode=intent.account_mode,
            contract_id=intent.contract_id,fingerprint=fingerprint(intent,account_id),approved_by=approved_by,
            expires_at=utc_now()+timedelta(minutes=10))
        with self.repo.db.transaction() as conn:
            order=self.repo.get(order.order_id,conn)
            conn.execute('INSERT INTO approvals VALUES(?,?,?,?,?)',
                (approval.approval_id,intent_id,account_id,approval.fingerprint,approval.model_dump_json()))
            if order.status == S.APPROVAL_REQUIRED:
                self.repo.transition(order.order_id,S.APPROVED,'human_approved',conn=conn)
        return approval

    def valid_approval(self, order, conn=None):
        if conn is None:
            with self.repo.db.transaction() as connection:
                return self.valid_approval(order, connection)
        row=conn.execute('SELECT raw_payload FROM trade_intents WHERE intent_id=?',(order.intent_id,)).fetchone()
        intent=TradeIntent.model_validate_json(row[0])
        rows=conn.execute('SELECT data_json FROM approvals WHERE intent_id=? AND account_id=?',
                          (intent.intent_id,order.account_id)).fetchall()
        return any((a:=Approval.model_validate_json(row[0])).expires_at>utc_now() and
                   a.fingerprint==fingerprint(intent,order.account_id) for row in rows)

    async def execute_trade(self, intent_id):
        order=await self.validate_trade(intent_id)
        if order.status not in {S.CREATED,S.VALIDATED,S.APPROVAL_REQUIRED,S.APPROVED}:
            return order
        intent=self.repo.intent(intent_id)
        if intent.account_mode == 'live':
            if os.getenv('DERIV_LIVE_WRITES_ENABLED') != '1' or (self.context.source=='mcp' and os.getenv('DERIV_MCP_LIVE_WRITES_ENABLED') != '1'):
                raise PermissionError('Live write capability is not enabled on this host')
        if not self.valid_approval(order):
            return order
        if order.status != S.APPROVED:
            return order
        self.context.require_time()
        if order.action == 'BUY':
            proposal=await self.adapter.get_proposal(intent)
            if (not proposal.proposal_id or not isinstance(proposal.ask_price,Decimal)
                    or not proposal.ask_price.is_finite() or not 0 < proposal.ask_price <= intent.amount):
                raise ValueError('Invalid proposal or price exceeds confirmed stake')
            # Update proposal without a status event: the submission claim still happens only once.
            with self.repo.db.transaction() as conn:
                old=self.repo.get(order.order_id,conn)
                if old.status == S.APPROVED:
                    updated=old.model_copy(update={'proposal_id':proposal.proposal_id})
                    conn.execute('UPDATE orders SET data_json=? WHERE order_id=?',(updated.model_dump_json(),order.order_id))
        self.context.require_time()
        try:
            account=await self.adapter.get_account()
            snapshot_at=time.monotonic()
            closed=await self.adapter.get_closed_contracts() if order.action=='BUY' else []
        except Exception:
            with self.repo.db.transaction() as conn:
                result=RiskResult(allowed=False,code='RISK_DATA_UNAVAILABLE',reason='Broker risk data is unavailable')
                conn.execute('INSERT INTO risk_events VALUES(?,?,?,?,?,?,?,?)',
                    (str(uuid4()),intent_id,order.order_id,0,result.code,result.reason,'{}',utc_now().isoformat()))
                old=self.repo.get(order.order_id,conn)
                if old.status==S.APPROVED:
                    return self.repo.transition(order.order_id,S.REJECTED,'risk_data_unavailable',changes={'last_error':result.code},conn=conn)
                return old
        def risk_check(conn, claimed):
            state=TradingState(conn.execute('SELECT state FROM trading_control WHERE singleton=1').fetchone()[0])
            if not self.valid_approval(claimed,conn):
                result=RiskResult(allowed=False,code='APPROVAL_EXPIRED',reason='Approval expired before submission')
            elif self.context.remaining_time <= 0:
                result=RiskResult(allowed=False,code='DEADLINE_EXHAUSTED',reason='Deadline exhausted before submission')
            elif account.account_id != claimed.account_id or account.mode != intent.account_mode:
                result=RiskResult(allowed=False,code='ACCOUNT_MISMATCH',reason='Authenticated account differs')
            elif claimed.action == 'SELL' and any(
                    other.order_id != claimed.order_id and other.action == 'SELL'
                    and other.contract_id == claimed.contract_id
                    for other in self.repo.list(claimed.account_id,
                        {S.SUBMITTING,S.ACKNOWLEDGED,S.UNKNOWN,S.RECONCILING,S.CLOSED},conn)):
                result=RiskResult(allowed=False,code='CONTRACT_CLOSE_IN_PROGRESS',reason='Contract close already submitted')
            elif time.monotonic()-snapshot_at>5:
                result=RiskResult(allowed=False,code='STALE_RISK_SNAPSHOT',reason='Risk snapshot is stale')
            else:
                snapshot=self.risk_snapshot(intent,account,closed,conn)
                result=self.risk_engine.evaluate(intent,snapshot,self.policy,state)
            conn.execute('INSERT INTO risk_events VALUES(?,?,?,?,?,?,?,?)',
                (str(uuid4()),intent_id,claimed.order_id,int(result.allowed),result.code,result.reason,
                 json.dumps({**result.metrics,'request_id':claimed.request_id,'correlation_id':claimed.correlation_id}),utc_now().isoformat()))
            if not result.allowed:
                old=claimed.model_copy(update={'last_error':result.code})
                conn.execute('UPDATE orders SET data_json=? WHERE order_id=?',(old.model_dump_json(),old.order_id))
            return result.allowed
        self.context.require_time()
        return await self.engine.execute(order.order_id,self.adapter,risk_check)

    def risk_snapshot(self, intent, account, closed, conn):
        portfolio={row.contract_id:row for row in account.contracts}
        reservations=self.repo.list(account.account_id,{S.SUBMITTING,S.ACKNOWLEDGED,S.OPEN,S.UNKNOWN,S.RECONCILING},conn)
        closed_ids={row.contract_id for row in closed}
        unreported=[order for order in reservations if order.contract_id not in closed_ids and order.action=='BUY' and order.contract_id not in portfolio]
        open_stake=sum((row.buy_price for row in portfolio.values()),Decimal(0))+sum((o.amount for o in unreported),Decimal(0))
        symbol_stake=sum((row.buy_price for row in portfolio.values() if row.symbol==intent.symbol),Decimal(0))+sum((o.amount for o in unreported if o.symbol==intent.symbol),Decimal(0))
        today=utc_now().replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        history=sorted(closed,key=lambda row:row.sell_time,reverse=True)
        profits=[row.sell_price-row.buy_price for row in history]
        daily_loss=max(Decimal(0),-sum((p for p,row in zip(profits,history) if row.sell_time>=today),Decimal(0)))
        consecutive=0
        for profit in profits:
            if profit>=0: break
            consecutive+=1
        last_loss=next((row.sell_time for row,p in zip(history,profits) if p<0),None)
        last_minute=utc_now()-timedelta(minutes=1)
        for settled in reservations:
            if settled.status==S.OPEN and settled.contract_id in closed_ids:
                self.repo.transition(settled.order_id,S.EXPIRED,'broker_natural_settlement',conn=conn)
        count=sum(order.submitted_at is not None and order.submitted_at>=last_minute for order in self.repo.list(account.account_id,conn=conn))
        return RiskSnapshot(balance=account.balance-sum((o.amount for o in unreported),Decimal(0)),open_stake=open_stake,open_contracts=len(portfolio)+len(unreported),
            symbol_exposure=symbol_stake,daily_loss=daily_loss,consecutive_losses=consecutive,
            seconds_since_loss=max(0.,time.time()-last_loss) if last_loss is not None else None,
            orders_last_minute=count,unresolved_order_count=sum(o.status in {S.UNKNOWN,S.RECONCILING} for o in reservations))

    def set_trading_state(self, state: TradingState):
        state=TradingState(state)
        with self.repo.db.transaction() as conn:
            conn.execute('UPDATE trading_control SET state=? WHERE singleton=1',(state.value,))
        return state

    async def confirm_and_execute(self, expected_intent: TradeIntent, *, approved_by='local-user'):
        stored=self.repo.intent(expected_intent.intent_id)
        if fingerprint(stored,'') != fingerprint(expected_intent,''):
            raise ValueError('Confirmation parameters do not match the immutable intent')
        order=await self.validate_trade(expected_intent.intent_id)
        if order.status in {S.APPROVAL_REQUIRED,S.APPROVED} and not self.valid_approval(order):
            self.approve_trade(expected_intent.intent_id,order.account_id,expected_intent=expected_intent,approved_by=approved_by)
        return await (self.close_trade(expected_intent.intent_id) if expected_intent.action=='SELL' else self.execute_trade(expected_intent.intent_id))

    async def refresh_order(self, order_id):
        order=self.repo.get(order_id)
        if order.status==S.UNKNOWN:
            return await self.reconcile_order(order_id)
        if order.status!=S.OPEN or order.contract_id is None:
            return order
        account=await self.adapter.get_account()
        if account.account_id!=order.account_id:
            raise AccountValidationError('account_authorization_unverified')
        contract=await self.adapter.get_contract(order.contract_id)
        if contract.is_sold:
            return self.repo.transition(order_id,S.EXPIRED if contract.is_expired else S.CLOSED,
                                        'broker_settled',expected=S.OPEN)
        return order

    async def close_trade(self, intent_id):
        if self.repo.intent(intent_id).action != 'SELL':
            raise ValueError('close_trade requires a SELL intent')
        return await self.execute_trade(intent_id)

    def get_order_status(self, order_id):
        return self.repo.get(order_id)

    async def reconcile_order(self, order_id):
        return await self.reconciler.reconcile(order_id,self.adapter)

    async def bind_reconciliation_contract(self, order_id, contract_id):
        order=self.repo.get(order_id)
        account=await self.adapter.get_account()
        if account.account_id!=order.account_id or order.status!=S.UNKNOWN:
            raise ValueError('Only an uncertain order for this account can be resolved')
        if order.contract_id is not None and order.contract_id != contract_id:
            raise ValueError('Cannot change the confirmed contract identity')
        contract=await self.adapter.get_contract(contract_id)
        if contract.contract_id!=contract_id:
            raise ValueError('Contract identity mismatch')
        # This is a local user's explicit identification after reviewing the broker statement.
        with self.repo.db.transaction() as conn:
            old=self.repo.get(order_id,conn)
            if old.status!=S.UNKNOWN: return old
            if old.contract_id is not None and old.contract_id != contract_id:
                raise ValueError('Cannot change the confirmed contract identity')
            updated=old.model_copy(update={'contract_id':contract_id})
            conn.execute('UPDATE orders SET contract_id=?,data_json=? WHERE order_id=?',(contract_id,updated.model_dump_json(),order_id))
            self.repo._event(conn,updated,old.status,'human_contract_binding',{'contract_id':contract_id})
        return await self.reconcile_order(order_id)

    async def recover_incomplete_orders(self):
        await self.adapter.get_account()
        return await self.reconciler.recover_incomplete_orders(self.adapter)


def trading_application(api_token, *, source='mcp', db_path=None, context=None):
    from server import DerivWebSocketClient
    from adapters.deriv.websocket import WebSocketDerivAdapter
    from persistence.database import DEFAULT_DB_PATH
    context=context or ExecutionContext(source)
    return TradingService(Database(db_path or os.getenv('DERIV_DB_PATH') or DEFAULT_DB_PATH),
                          WebSocketDerivAdapter(api_token,DerivWebSocketClient,context),context)
