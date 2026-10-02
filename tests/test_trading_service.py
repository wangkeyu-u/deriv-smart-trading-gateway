import asyncio
from decimal import Decimal
import pytest

from domain.order import OrderStatus as S
from domain.trade import TradeIntent
from persistence.database import Database
from services.context import ExecutionContext
from services.trading_service import TradingService
from tests.test_order_engine import Broker
from adapters.deriv.models import AccountSnapshot, Proposal
from domain.trade import TradingMode


class Adapter(Broker):
    account_id='VRTC1'
    def __init__(self, mode='demo'): super().__init__(); self.mode=mode
    async def get_account(self): return AccountSnapshot(self.account_id,TradingMode(self.mode),Decimal('1000'),'USD')
    async def get_proposal(self,intent): return Proposal('p',Decimal('10'))
    async def get_closed_contracts(self): return []


@pytest.fixture
def service(tmp_path):
    return TradingService(Database(tmp_path/'service.sqlite3'),Adapter(),ExecutionContext('streamlit'))


def create(service, mode='demo'):
    intent=TradeIntent(action='BUY',symbol='R_100',direction='CALL',amount=Decimal('10'),duration=5,
        duration_unit='t',account_mode=mode,source='streamlit')
    service.create_trade_intent(intent)
    return intent


def test_approval_is_persistent_and_parameter_bound(service):
    intent=create(service)
    order=asyncio.run(service.execute_trade(intent.intent_id))
    assert order.status==S.APPROVAL_REQUIRED and service.adapter.buys==0
    with pytest.raises(ValueError,match='parameters'):
        service.approve_trade(intent.intent_id,'VRTC1',expected_intent=intent.model_copy(update={'amount':Decimal('100')}))
    service.approve_trade(intent.intent_id,'VRTC1',expected_intent=intent)
    reopened=TradingService(Database(service.repo.db.path),service.adapter,ExecutionContext('streamlit'))
    assert asyncio.run(reopened.execute_trade(intent.intent_id)).status==S.OPEN
    assert asyncio.run(reopened.execute_trade(intent.intent_id)).status==S.OPEN
    assert service.adapter.buys==1


def test_mcp_live_write_requires_host_capability_and_approval(service,monkeypatch):
    service.context=ExecutionContext('mcp')
    service.adapter.mode='live'
    intent=create(service,'live')
    with pytest.raises(PermissionError): asyncio.run(service.execute_trade(intent.intent_id))
    monkeypatch.setenv('DERIV_LIVE_WRITES_ENABLED','1')
    with pytest.raises(PermissionError): asyncio.run(service.execute_trade(intent.intent_id))
    monkeypatch.setenv('DERIV_MCP_LIVE_WRITES_ENABLED','1')
    assert asyncio.run(service.execute_trade(intent.intent_id)).status==S.APPROVAL_REQUIRED
    assert service.adapter.buys==0


def test_approval_expiration_is_rechecked_at_submit_claim(service,monkeypatch):
    intent=create(service)
    order=asyncio.run(service.validate_trade(intent.intent_id))
    service.approve_trade(intent.intent_id,order.account_id,expected_intent=intent)
    async def expire_during_preflight():
        with service.repo.db.transaction() as conn:
            conn.execute('DELETE FROM approvals')
        return []
    monkeypatch.setattr(service.adapter,'get_closed_contracts',expire_during_preflight)
    result=asyncio.run(service.execute_trade(intent.intent_id))
    assert result.status==S.REJECTED and result.last_error=='APPROVAL_EXPIRED'
    assert service.adapter.buys==0


def test_streamlit_and_mcp_share_configured_database_from_another_cwd(tmp_path,monkeypatch):
    import subprocess
    import sys
    import os
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    path=tmp_path/'nested'/'shared.sqlite3'
    env=os.environ.copy(); env['DERIV_DB_PATH']=str(path); env['PYTHONPATH']=str(root)
    code="import web_app; from services.trading_service import trading_application; print(web_app.DB_PATH); print(trading_application('unused').repo.db.path)"
    result=subprocess.run([sys.executable,'-c',code],cwd=tmp_path,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert result.stdout.splitlines()==[str(path),str(path)]
