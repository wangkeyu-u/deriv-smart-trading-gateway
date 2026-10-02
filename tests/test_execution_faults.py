"""Fault injection through the real application, adapter and MCP boundaries."""
import asyncio
import json
import time
from decimal import Decimal
from uuid import uuid4

import pytest
import server
from domain.order import OrderStatus as S
from domain.risk import TradingState
from domain.trade import TradeIntent
from execution.engine import OrderEngine
from services.trading_service import trading_application


class FakeDeriv:
    buys=0
    sells=0
    committed=False
    timeout=False
    before_send=False
    loginid='VRTC1'
    sold=False
    authorization={}
    def __init__(self, **kwargs): self.authorization={'loginid':type(self).loginid,'currency':'USD'}
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    async def request(self,payload,**kwargs):
        cls=type(self)
        if 'balance' in payload: return {'balance':{'balance':1000}}
        if 'portfolio' in payload: return {'portfolio':{'contracts':[{'contract_id':42,'symbol':'R_100','buy_price':10}] if cls.committed and not cls.sold else []}}
        if 'proposal' in payload: return {'proposal':{'id':'proposal-1','ask_price':10}}
        if 'buy' in payload:
            assert kwargs['retries']==0
            if cls.before_send: raise server.DerivNotSentError('Before send')
            cls.buys+=1; cls.committed=True
            if cls.timeout: raise server.DerivTimeoutError('After send')
            return {'buy':{'contract_id':42,'transaction_id':43,'buy_price':10}}
        if 'sell' in payload:
            cls.sells+=1; cls.sold=True
            return {'sell':{'contract_id':42,'transaction_id':44,'sold_for':9}}
        if 'profit_table' in payload: return {'profit_table':{'transactions':[]}}
        if 'statement' in payload: return {'statement':{'transactions':[{'contract_id':42,'proposal_id':'proposal-1'}] if cls.committed else []}}
        if 'proposal_open_contract' in payload: return {'proposal_open_contract':{'contract_id':42,'is_sold':int(cls.sold),'is_expired':0}}
        raise AssertionError(payload)


@pytest.fixture
def broker(monkeypatch):
    for name,value in dict(buys=0,sells=0,committed=False,timeout=False,before_send=False,loginid='VRTC1',sold=False).items():
        setattr(FakeDeriv,name,value)
    monkeypatch.setattr(server,'DerivWebSocketClient',FakeDeriv)
    return FakeDeriv


def approved(broker,action='BUY',mode='demo',source='streamlit'):
    service=trading_application('fake-token',source=source)
    intent=TradeIntent(intent_id=str(uuid4()),action=action,symbol='R_100',direction='CALL' if action=='BUY' else None,
        amount=Decimal('10') if action=='BUY' else Decimal(0),duration=5 if action=='BUY' else 0,duration_unit='t',
        contract_id=42 if action=='SELL' else None,account_mode=mode,source=source)
    service.create_trade_intent(intent)
    order=asyncio.run(service.validate_trade(intent.intent_id))
    service.approve_trade(intent.intent_id,order.account_id,expected_intent=intent)
    return service,intent,order


def test_server_commit_timeout_then_reconciliation_buys_once(broker):
    service,intent,order=approved(broker)
    broker.timeout=True
    assert asyncio.run(service.execute_trade(intent.intent_id)).status==S.UNKNOWN
    service=trading_application('fake-token',source='streamlit')
    assert asyncio.run(service.reconcile_order(order.order_id)).status==S.OPEN
    asyncio.run(service.execute_trade(intent.intent_id))
    assert broker.buys==1


def test_proven_before_send_is_rejected_without_buy(broker):
    service,intent,_=approved(broker)
    broker.before_send=True
    assert asyncio.run(service.execute_trade(intent.intent_id)).status==S.REJECTED
    assert broker.buys==0


def test_mcp_duplicate_approved_request_has_one_buy(broker):
    service,intent,_=approved(broker)
    async def request():
        return json.loads(await server.place_contract('fake-token','R_100',10.,'CALL',5,'t',intent_id=intent.intent_id))
    assert asyncio.run(request())['ok'] is True
    assert asyncio.run(request())['ok'] is True
    assert broker.buys==1
    with service.repo.db.transaction() as conn:
        assert conn.execute('SELECT count(*) FROM order_receipts').fetchone()[0]==1


def test_mcp_cannot_bypass_live_capability_even_with_approval_and_flag(broker):
    broker.loginid='CR1'
    service,intent,_=approved(broker,mode='live')
    result=json.loads(asyncio.run(server.place_contract('fake-token','R_100',10.,'CALL',5,'t',True,'live',intent.intent_id)))
    assert result['ok'] is False and broker.buys==0


def test_mcp_enabled_live_still_requires_approval(broker,monkeypatch):
    broker.loginid='CR1'
    monkeypatch.setenv('DERIV_LIVE_WRITES_ENABLED','1'); monkeypatch.setenv('DERIV_MCP_LIVE_WRITES_ENABLED','1')
    service,intent,order=approved(broker,mode='live')
    with service.repo.db.transaction() as conn: conn.execute('DELETE FROM approvals')
    result=json.loads(asyncio.run(server.place_contract('fake-token','R_100',10.,'CALL',5,'t',True,'live',intent.intent_id)))
    assert result['ok'] is False and broker.buys==0


def test_mcp_stake_change_is_rejected_before_write(broker):
    service,intent,_=approved(broker)
    result=json.loads(asyncio.run(server.place_contract('fake-token','R_100',100.,'CALL',5,'t',intent_id=intent.intent_id)))
    assert result['ok'] is False and broker.buys==0


def test_halted_allows_approved_close_and_updates_open_order(broker):
    service,intent,parent=approved(broker)
    assert asyncio.run(service.execute_trade(intent.intent_id)).status==S.OPEN
    sell_service,sell,order=approved(broker,action='SELL')
    sell_service.set_trading_state(TradingState.HALTED)
    assert asyncio.run(sell_service.close_trade(sell.intent_id)).status==S.CLOSED
    assert service.repo.get(parent.order_id).status==S.CLOSED
    assert broker.buys==1 and broker.sells==1


def test_validation_error_never_exposes_secret(broker):
    secret='FULL-SECRET-TEST-TOKEN'
    result=asyncio.run(server.place_contract(secret,'R_100',-1.,'CALL',5,'t'))
    assert secret not in result


def test_risk_data_failure_is_recorded_without_submission(broker,monkeypatch):
    service,intent,order=approved(broker)
    async def fail(): raise TimeoutError('unavailable')
    monkeypatch.setattr(service.adapter,'get_closed_contracts',fail)
    result=asyncio.run(service.execute_trade(intent.intent_id))
    assert result.status==S.REJECTED and result.last_error=='RISK_DATA_UNAVAILABLE'
    assert broker.buys==0
    with service.repo.db.transaction() as conn:
        assert conn.execute('SELECT code FROM risk_events').fetchone()[0]=='RISK_DATA_UNAVAILABLE'


def test_natural_expiry_refresh_updates_order(broker):
    service,intent,order=approved(broker)
    asyncio.run(service.execute_trade(intent.intent_id))
    from adapters.deriv.models import ContractSnapshot
    async def expired(cid): return ContractSnapshot(cid,True,True)
    service.adapter.get_contract=expired
    assert asyncio.run(service.refresh_order(order.order_id)).status==S.EXPIRED


def test_ui_confirmation_executes_service_once_and_preserves_global_halt(broker):
    import hashlib
    from streamlit.testing.v1 import AppTest
    service=trading_application('fake-token',source='streamlit')
    intent=TradeIntent(action='BUY',symbol='R_100',direction='CALL',amount=Decimal('10'),duration=5,
                       duration_unit='t',account_mode='demo',source='streamlit')
    service.create_trade_intent(intent)
    ui=AppTest.from_string('import web_app\nweb_app.init_state()\nweb_app.render_trade_controls()',default_timeout=5).run()
    ui.session_state['deriv_token']='fake-token'
    ui.session_state['pending_trade']={'action':'place_contract','symbol':'R_100','amount':10.0,'contract_type':'CALL',
        'duration':5,'duration_unit':'t','contract_id':None,'allow_live':False,'intent_id':intent.intent_id,
        'credential_id':hashlib.sha256(b'fake-token').hexdigest()}
    ui.run()
    ui.checkbox[0].check().run()
    next(button for button in ui.button if button.label=='确认并提交').click().run()
    assert not ui.exception
    assert service.repo.by_intent(intent.intent_id).status==S.OPEN and broker.buys==1
    ui.run()
    assert broker.buys==1
    service.set_trading_state(TradingState.HALTED)
    ui.run()
    assert not ui.exception
    with service.repo.db.transaction() as conn:
        assert conn.execute('SELECT state FROM trading_control').fetchone()[0]=='HALTED'
        assert conn.execute('SELECT count(*) FROM trade_receipts').fetchone()[0]==1
