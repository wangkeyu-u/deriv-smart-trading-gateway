from decimal import Decimal

import pytest
from pydantic import ValidationError

from domain.market import ObservedTrend
from domain.order import OrderStatus
from domain.trade import TradeIntent


def intent(**changes):
    return TradeIntent(**(dict(action="BUY", symbol="R_100", direction="CALL", amount=Decimal("10.00"),
                              duration=5, duration_unit="m", account_mode="demo", source="streamlit") | changes))


def test_intent_is_strict_and_not_an_order():
    trade = intent()
    assert trade.amount == Decimal("10.00")
    assert trade.created_at.tzinfo is not None
    assert not hasattr(trade, "status")
    for change in ({"amount": 10.0}, {"amount": Decimal("NaN")}, {"duration": True}, {"direction": "UP"}, {"secret": "token"}):
        with pytest.raises(ValidationError):
            intent(**change)
    assert set(ObservedTrend) == {"UP", "DOWN", "FLAT", "UNKNOWN"}
    assert OrderStatus.UNKNOWN != OrderStatus.REJECTED


def test_sell_has_contract_identity_not_direction():
    assert intent(action="SELL", direction=None, amount=Decimal(0), duration=0, contract_id=42).contract_id == 42
    with pytest.raises(ValidationError):
        intent(action="SELL", contract_id=42)


@pytest.mark.parametrize("loginid,mode,allow,accepted", [
    ("VRTC123", "demo", False, True), ("CR123", "demo", True, False),
    ("VRTC123", "live", True, False), ("CR123", "live", False, False), ("CR123", "live", True, True),
])
def test_place_contract_mode_is_bound_to_authorized_account(monkeypatch, loginid, mode, allow, accepted):
    import asyncio
    import json
    import server
    calls = []
    class Client:
        authorization = {"loginid": loginid, "currency": "USD"}
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, payload, **kwargs):
            calls.append(payload)
            return {"proposal": {"id": "p", "ask_price": 10}} if "proposal" in payload else {"buy": {"contract_id": 42}}
    monkeypatch.setattr(server, "DerivWebSocketClient", Client)
    from services.context import ExecutionContext
    from adapters.deriv.websocket import WebSocketDerivAdapter
    trade = intent(account_mode=mode)
    adapter = WebSocketDerivAdapter('test', Client, ExecutionContext('streamlit'))
    if loginid.startswith('VRTC') != (mode == 'demo'):
        with pytest.raises(Exception, match='mode mismatch'):
            asyncio.run(adapter.get_proposal(trade))
    else:
        assert asyncio.run(adapter.get_proposal(trade)).proposal_id == 'p'
    assert not any('buy' in call for call in calls)
    result=json.loads(asyncio.run(server.place_contract('test','R_100',10.0,'CALL',5,'t',allow,mode)))
    assert result['ok'] is False  # Neither demo nor live can bypass persistent approval.
