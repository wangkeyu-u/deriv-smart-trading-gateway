"""Broker boundary. Business code never builds Deriv request JSON."""
import asyncio
from decimal import Decimal

from domain.trade import TradingMode
from adapters.deriv.models import AccountSnapshot, OpenPosition, ClosedContract, Proposal, ContractSnapshot, ReconciliationResult
from execution.engine import NotSentError, BrokerRejectedError, UnknownOutcomeError


class WebSocketDerivAdapter:
    def __init__(self, api_token, client_factory, context):
        self._token = api_token
        self._factory = client_factory
        self.context = context
        self.account_id = None
        self.account_mode = None

    def client(self):
        self.context.require_time()
        return self._factory(api_token=self._token, max_retries=0,
                             timeout_seconds=min(5, self.context.remaining_time))

    def _authorize(self, client):
        from server import account_type_from_authorize
        auth = client.authorization or {}
        account_id = auth.get('loginid') or auth.get('account')
        mode = account_type_from_authorize(auth)
        if not account_id or mode not in {'demo','live'}:
            raise NotSentError('Unverified account')
        if self.account_id and self.account_id != account_id:
            raise NotSentError('Account changed')
        self.account_id, self.account_mode = str(account_id), TradingMode(mode)
        return auth

    async def get_account(self):
        async def read():
            async with self.client() as client:
                auth = self._authorize(client)
                balance = (await client.request({'balance':1,'subscribe':0}, retries=0)).get('balance', {})
                portfolio = (await client.request({'portfolio':1}, retries=0)).get('portfolio', {})
                if not isinstance(portfolio.get('contracts'),list):
                    raise ValueError('Incomplete portfolio response')
                if balance.get('loginid') and balance['loginid']!=self.account_id:
                    raise ValueError('Balance account mismatch')
                return AccountSnapshot(self.account_id,self.account_mode,Decimal(str(balance['balance'])),auth['currency'],
                    tuple(OpenPosition(int(row['contract_id']),row['symbol'],Decimal(str(row['buy_price'])),row.get('contract_type')) for row in portfolio.get('contracts',[])))
        return await asyncio.wait_for(read(), self.context.remaining_time)

    async def get_proposal(self, intent):
        async def read():
            async with self.client() as client:
                auth=self._authorize(client)
                if self.account_mode != intent.account_mode:
                    raise NotSentError('Account mode mismatch')
                response=await client.request({'proposal':1,'amount':float(intent.amount),'basis':'stake',
                    'contract_type':intent.direction.value,'currency':auth.get('currency'), 'duration':intent.duration,
                    'duration_unit':intent.duration_unit,'symbol':intent.symbol}, retries=0)
                proposal=response.get('proposal') or {}
                if not proposal.get('id') or not isinstance(proposal.get('ask_price'), (int,float)) or isinstance(proposal['ask_price'],bool):
                    raise NotSentError('Invalid proposal')
                price=Decimal(str(proposal['ask_price']))
                if not price.is_finite() or price <= 0 or price > intent.amount:
                    raise NotSentError('Proposal price exceeds approved stake')
                return Proposal(str(proposal['id']),price)
        return await asyncio.wait_for(read(), self.context.remaining_time)

    async def _write(self, intent, order, payload, response_key):
        # A dedicated write timeout starts after the durable SUBMITTING claim. No outer read deadline cancels it.
        attempted=False
        try:
            async with self._factory(api_token=self._token, max_retries=0, timeout_seconds=5) as client:
                auth=self._authorize(client)
                if self.account_id != order.account_id or self.account_mode != intent.account_mode:
                    raise NotSentError('Account mismatch')
                attempted=True
                response=await client.request(payload, retries=0)
                result=response.get(response_key) or {}
                if response_key=='buy' and (type(result.get('contract_id')) is not int or result['contract_id']<=0):
                    raise UnknownOutcomeError('Missing contract_id')
                safe={key:result[key] for key in ('contract_id','transaction_id','buy_price','purchase_price','sold_for','sell_price','longcode','start_time') if key in result}
                return {**safe,'contract_id':result.get('contract_id') or intent.contract_id,
                        'transaction_id':result.get('transaction_id'), 'symbol':intent.symbol,
                        'contract_type':intent.direction.value if intent.direction else None,
                        'purchase_price':result.get('buy_price'), 'currency':auth.get('currency'),
                        'account_type':self.account_mode.value, 'loginid':self.account_id}
        except NotSentError:
            raise
        except Exception as exc:
            from server import DerivAPIError, DerivNotSentError
            if isinstance(exc, DerivAPIError) and attempted:
                raise BrokerRejectedError('Broker explicitly rejected request') from exc
            if isinstance(exc, DerivNotSentError) or not attempted:
                raise NotSentError('Write not sent') from exc
            raise UnknownOutcomeError('Write outcome unknown') from exc

    async def place_order(self, intent, order):
        return await self._write(intent,order,{'buy':order.proposal_id, 'price':float(intent.amount),
            'passthrough':{'order_id':order.order_id,'intent_id':order.intent_id,'correlation_id':order.correlation_id}}, 'buy')

    async def close_order(self, intent, order):
        return await self._write(intent,order,{'sell':intent.contract_id,'price':0,
            'passthrough':{'order_id':order.order_id,'intent_id':order.intent_id}}, 'sell')

    async def get_contract(self, contract_id):
        async def read():
            async with self.client() as client:
                self._authorize(client)
                raw=(await client.request({'proposal_open_contract':1,'contract_id':contract_id}, retries=0)).get('proposal_open_contract',{})
                return ContractSnapshot(int(raw['contract_id']),bool(raw.get('is_sold')),bool(raw.get('is_expired')),raw)
        return await asyncio.wait_for(read(), self.context.remaining_time)

    async def get_statement(self, since):
        async def read():
            async with self.client() as client:
                self._authorize(client)
                return (await client.request({'statement':1,'date_from':since,'limit':100}, retries=0)).get('statement',{}).get('transactions',[])
        return await asyncio.wait_for(read(), self.context.remaining_time)

    async def get_closed_contracts(self):
        from datetime import datetime, timezone
        today=int(datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
        async def read():
            async with self.client() as client:
                self._authorize(client)
                rows=[]
                # Fetch all of today plus enough recent trades to determine a loss streak.
                for offset in range(0,2000,100):
                    response=await client.request({'profit_table':1,'description':1,'limit':100,'offset':offset,'sort':'DESC'},retries=0)
                    batch=response.get('profit_table',{}).get('transactions')
                    if not isinstance(batch,list):
                        raise ValueError('Missing broker profit history')
                    rows.extend(batch)
                    if len(batch)<100 or (len(rows)>=100 and min(float(r['sell_time']) for r in batch)<today):
                        return [ClosedContract(int(r['contract_id']),Decimal(str(r['buy_price'])),Decimal(str(r['sell_price'])),float(r['sell_time'])) for r in rows]
                raise ValueError('Profit history exceeds bounded page limit')
        return await asyncio.wait_for(read(),self.context.remaining_time)

    async def resolve_order(self, order, intent):
        account=await self.get_account()
        if account.account_id != order.account_id:
            return ReconciliationResult(False)
        if order.contract_id:
            contract=await self.get_contract(order.contract_id)
            if contract.contract_id != order.contract_id or (order.action=='SELL' and not contract.is_sold):
                return ReconciliationResult(False)
            return ReconciliationResult(True,'EXPIRED' if contract.is_expired and contract.is_sold else 'CLOSED' if contract.is_sold else 'OPEN',
                {'contract_id':order.contract_id,'transaction_id':order.transaction_id})
        transactions=await self.get_statement(int((order.submitted_at or order.created_at).timestamp())-60)
        # Statement passthrough/proposal IDs are optional. Similar-looking trades aren't proof.
        candidates=[row for row in transactions if
                    (row.get('passthrough') or {}).get('order_id')==order.order_id or
                    (order.proposal_id and row.get('proposal_id')==order.proposal_id)]
        identities={int(row['contract_id']) for row in candidates if row.get('contract_id')}
        if len(identities)==1:
            cid=next(iter(identities)); contract=await self.get_contract(cid)
            if contract.contract_id==cid:
                return ReconciliationResult(True,'EXPIRED' if contract.is_expired and contract.is_sold else 'CLOSED' if contract.is_sold else 'OPEN',{'contract_id':cid})
        return ReconciliationResult(False)

    async def sync_server_time(self):
        import time
        begin=time.time()
        async with self.client() as client:
            response=await asyncio.wait_for(client.request({'time':1},retries=0),self.context.remaining_time)
        end=time.time()
        self.server_time_offset_seconds=float(response['time'])-(begin+end)/2
        return {'server_time_offset_seconds':self.server_time_offset_seconds,'uncertainty_seconds':(end-begin)/2}

    async def get_open_contracts(self):
        return (await self.get_account()).contracts

    async def get_tick(self, symbol, subscribe=False):
        from adapters.deriv.client import extract_tick
        async def read():
            async with self.client() as client:
                first=await client.request({'ticks':symbol,**({'subscribe':1} if subscribe else {})},retries=0)
                sid=(first.get('subscription') or {}).get('id')
                stream=await client.collect_subscription(sid) if subscribe and sid else []
                return {'tick':extract_tick(first),'subscription_id':sid,'stream_sample':[extract_tick(row) for row in stream]}
        return await asyncio.wait_for(read(),self.context.remaining_time)

    async def get_candles(self,symbol,granularity,count):
        from adapters.deriv.client import normalize_candles
        async def read():
            async with self.client() as client:
                return normalize_candles(await client.request({'ticks_history':symbol,'adjust_start_time':1,'count':count,
                    'end':'latest','granularity':granularity,'style':'candles'},retries=0))
        return await asyncio.wait_for(read(),self.context.remaining_time)
