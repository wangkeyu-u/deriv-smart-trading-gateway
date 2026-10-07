import asyncio
from decimal import Decimal
import pytest
from domain.risk import TradingState, RiskSnapshot
from risk.engine import RiskEngine
from risk.policy import RiskPolicy
from domain.order import OrderStatus as S
from tests.test_trading_service import create, service


def snapshot(**changes):
    return RiskSnapshot(**(dict(balance=Decimal('1000'),open_stake=Decimal(0),open_contracts=0,
        symbol_exposure=Decimal(0),daily_loss=Decimal(0),consecutive_losses=0,seconds_since_loss=None,
        orders_last_minute=0,unresolved_order_count=0)|changes))


@pytest.mark.parametrize('changes,code',[
    ({'open_stake':Decimal('195')},'MAX_TOTAL_OPEN_STAKE'), ({'open_contracts':5},'MAX_OPEN_CONTRACTS'),
    ({'symbol_exposure':Decimal('95')},'MAX_SYMBOL_EXPOSURE'), ({'daily_loss':Decimal('50')},'MAX_DAILY_LOSS'),
    ({'consecutive_losses':3},'MAX_CONSECUTIVE_LOSSES'), ({'seconds_since_loss':30.},'LOSS_COOLDOWN'),
    ({'balance':Decimal('15')},'MIN_AVAILABLE_BALANCE'), ({'orders_last_minute':5},'MAX_ORDER_RATE'),
    ({'unresolved_order_count':1},'UNRESOLVED_ORDER')])
def test_deterministic_limits(service,changes,code):
    result=RiskEngine().evaluate(create(service),snapshot(**changes),RiskPolicy())
    assert not result.allowed and result.code==code


def test_halt_persists_and_covers_all_buy_sources(service):
    service.set_trading_state(TradingState.HALTED)
    intent=create(service)
    order=asyncio.run(service.validate_trade(intent.intent_id))
    service.approve_trade(intent.intent_id,order.account_id,expected_intent=intent)
    assert asyncio.run(service.execute_trade(intent.intent_id)).status==S.REJECTED
    assert service.adapter.buys==0
    with service.repo.db.transaction() as conn:
        row=conn.execute('SELECT * FROM risk_events').fetchone()
        assert row['allowed']==0 and row['code']=='TRADING_HALTED'
    sell=intent.model_copy(update={'action':__import__('domain.trade',fromlist=['TradeAction']).TradeAction.SELL,'direction':None,'contract_id':42})
    assert RiskEngine().evaluate(sell,snapshot(),RiskPolicy(),TradingState.HALTED).allowed


@pytest.mark.parametrize('update,code', [({'amount':Decimal('51')},'MAX_STAKE_PER_TRADE'),
    ({'symbol':'FORBIDDEN'},'SYMBOL_NOT_ALLOWED'), ({'duration':11},'MAX_DURATION')])
def test_intent_limits(service,update,code):
    intent=create(service).model_copy(update=update)
    assert RiskEngine().evaluate(intent,snapshot(),RiskPolicy()).code==code


def test_reduce_only_and_contract_type_limit(service):
    intent=create(service)
    assert RiskEngine().evaluate(intent,snapshot(),RiskPolicy(),TradingState.REDUCE_ONLY).code=='REDUCE_ONLY'
    assert RiskEngine().evaluate(intent,snapshot(),RiskPolicy(allowed_contract_types=('PUT',))).code=='CONTRACT_NOT_ALLOWED'


def test_concurrent_distinct_orders_reserve_exposure_atomically(service):
    from concurrent.futures import ThreadPoolExecutor
    from domain.trade import TradeIntent
    from services.trading_service import TradingService
    from services.context import ExecutionContext
    from persistence.database import Database
    intents=[]
    for _ in range(2):
        intent=create(service)
        order=__import__('asyncio').run(service.validate_trade(intent.intent_id))
        service.approve_trade(intent.intent_id,order.account_id,expected_intent=intent)
        intents.append(intent)
    def execute(intent):
        instance=TradingService(Database(service.repo.db.path),service.adapter,ExecutionContext('streamlit'))
        instance.policy=RiskPolicy(max_total_open_stake=Decimal('10'))
        return asyncio.run(instance.execute_trade(intent.intent_id))
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(execute,intents))
    assert {result.status for result in results}=={S.OPEN,S.REJECTED}
    assert service.adapter.buys==1
