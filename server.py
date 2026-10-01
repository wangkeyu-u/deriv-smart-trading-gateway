"""Deriv Smart Trading Gateway MCP server.

This server exposes a small, strictly typed FastMCP tool surface for reading
Deriv market data and executing token-authenticated demo/live contract buys.
Use demo Deriv tokens for simulated trading workflows.
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
from datetime import datetime, timezone
from itertools import count
from typing import Any, Literal

import certifi
import pandas as pd
import websockets
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from typing_extensions import Annotated
from websockets.exceptions import ConnectionClosed, WebSocketException
from domain.trade import TradingMode
from adapters.deriv.client import (DerivWebSocketClient, GatewayError, DerivAPIError, DerivTimeoutError, DerivNotSentError, extract_tick, normalize_candles, summarize_portfolio, deriv_error_message)


APP_ID = os.getenv("DERIV_APP_ID", "1089")
DERIV_WS_URL_TEMPLATE = os.getenv(
    "DERIV_WS_URL_TEMPLATE",
    "wss://ws.derivws.com/websockets/v3?app_id={app_id}",
)
REQUEST_TIMEOUT_SECONDS = 5.0
SUBSCRIPTION_SAMPLE_SIZE = 5

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Granularity = Literal[60, 300, 3600]
ContractType = Literal["CALL", "PUT"]
DurationUnit = Literal["m", "h", "t"]


mcp = FastMCP("Deriv Smart Trading Gateway")


class MarketTicksInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    symbol: NonEmptyString
    subscribe: bool = False


class HistoricalCandlesInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    symbol: NonEmptyString
    granularity: Granularity
    count: Annotated[int, Field(ge=1, le=1000)]


class PlaceContractInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    api_token: NonEmptyString
    symbol: NonEmptyString
    amount: Annotated[float, Field(gt=0)]
    contract_type: ContractType
    duration: Annotated[int, Field(ge=1)]
    duration_unit: DurationUnit
    allow_live: bool = False
    trading_mode: Literal["demo", "live"] = "demo"


class AccountStatusInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    api_token: NonEmptyString


class OpenContractStatusInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    api_token: NonEmptyString
    contract_id: Annotated[int, Field(ge=1)] | None = None


class CloseContractInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    api_token: NonEmptyString
    contract_id: Annotated[int, Field(ge=1)]
    price: Annotated[float, Field(ge=0)] = 0.0
    allow_live: bool = False


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_secret(value: str | None) -> str | None:
    if not value:
        return value
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-3:]}"


def account_type_from_authorize(authorize: dict[str, Any]) -> str:
    loginid = str(authorize.get("loginid") or authorize.get("account") or "")
    landing_company = str(authorize.get("landing_company_name") or "").lower()
    if loginid.upper().startswith("VRTC") or "virtual" in landing_company:
        return "demo"
    if loginid:
        return "live"
    return "unknown"


def enforce_demo_or_explicit_live(authorize: dict[str, Any], allow_live: bool) -> str:
    account_type = account_type_from_authorize(authorize)
    if account_type == "unknown":
        raise DerivAPIError("Account type is unverified; execution is blocked")
    if account_type == "live" and not allow_live:
        raise DerivAPIError(
            "Live account execution is blocked by default. Use a demo token, "
            "or explicitly set allow_live=true after human confirmation."
        )
    return account_type


def clean_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def ok_response(tool: str, data: dict[str, Any]) -> str:
    return clean_json(
        {
            "ok": True,
            "tool": tool,
            "timestamp": utc_now_iso(),
            "data": data,
        }
    )


def error_response(tool: str, error: Exception | str) -> str:
    if isinstance(error, ValidationError):
        message = "Input validation failed"
        details: Any = error.errors(include_input=False, include_context=False)
        error_type = "validation_error"
    else:
        message = str(error)
        details = None
        error_type = error.__class__.__name__ if isinstance(error, Exception) else "error"

    return clean_json(
        {
            "ok": False,
            "tool": tool,
            "timestamp": utc_now_iso(),
            "error": {
                "type": error_type,
                "message": message,
                "details": details,
            },
        }
    )


def read_adapter(api_token=None):
    from services.context import ExecutionContext
    from adapters.deriv.websocket import WebSocketDerivAdapter
    return WebSocketDerivAdapter(api_token,DerivWebSocketClient,ExecutionContext('mcp'))


@mcp.tool()
async def get_market_ticks(symbol: str, subscribe: bool = False) -> str:
    try:
        params=MarketTicksInput.model_validate({'symbol':symbol,'subscribe':subscribe})
        result=await read_adapter().get_tick(params.symbol,params.subscribe)
        return ok_response('get_market_ticks',{'symbol':params.symbol,'subscribe':params.subscribe,
            **result,'stream_sample_limit':SUBSCRIPTION_SAMPLE_SIZE,'timeout_seconds':REQUEST_TIMEOUT_SECONDS})
    except Exception as exc:
        return error_response('get_market_ticks',exc)


@mcp.tool()
async def get_historical_candles(symbol: str, granularity: int, count: int) -> str:
    try:
        params=HistoricalCandlesInput.model_validate({'symbol':symbol,'granularity':granularity,'count':count})
        rows=await read_adapter().get_candles(params.symbol,params.granularity,params.count)
        return ok_response('get_historical_candles',{'symbol':params.symbol,'granularity':params.granularity,
            'requested_count':params.count,'returned_count':len(rows),'ohlcv':rows})
    except Exception as exc:
        return error_response('get_historical_candles',exc)


def order_response(tool, order):
    from domain.order import OrderStatus
    data = {"order": order.model_dump(mode="json"), "receipt": order.receipt}
    if order.status in {OrderStatus.OPEN, OrderStatus.CLOSED, OrderStatus.EXPIRED}:
        return ok_response(tool, data)
    return clean_json({"ok":False,"tool":tool,"timestamp":utc_now_iso(),"data":data,
                      "error":{"type":order.status.value,"message":f"Order status: {order.status.value}"}})


@mcp.tool()
async def place_contract(api_token: str, symbol: str, amount: float, contract_type: str,
                         duration: int, duration_unit: str, allow_live: bool = False,
                         trading_mode: str = "demo", intent_id: str | None = None) -> str:
    """Submit an existing locally approved intent. Live capability is disabled by default.

    intent_id is mandatory for writes. allow_live alone grants no execution authority.
    Create an intent first, then confirm it in the local workbench.
    """
    from decimal import Decimal
    from domain.trade import TradeIntent
    from services.trading_service import trading_application
    tool="place_contract"
    try:
        params=PlaceContractInput.model_validate(dict(api_token=api_token,symbol=symbol,amount=amount,
            contract_type=contract_type,duration=duration,duration_unit=duration_unit,
            allow_live=allow_live,trading_mode=trading_mode))
        if not intent_id:
            raise ValueError("intent_id is required; create and approve an intent before submitting")
        service=trading_application(params.api_token,source='mcp')
        original=service.repo.intent(intent_id)
        expected=TradeIntent(intent_id=intent_id,action='BUY',symbol=params.symbol,direction=params.contract_type,
            amount=Decimal(str(params.amount)),duration=params.duration,duration_unit=params.duration_unit,
            account_mode=params.trading_mode,source='mcp')
        from persistence.repositories import fingerprint
        if fingerprint(original,'') != fingerprint(expected,''):
            raise ValueError('Execution parameters do not match the approved intent')
        return order_response(tool,await service.execute_trade(intent_id))
    except Exception as exc:
        return error_response(tool,exc)


@mcp.tool()
async def create_trade_intent(api_token: str, payload: str) -> str:
    """Create and validate a strict intent; returns APPROVAL_REQUIRED, never sends buy/sell."""
    from domain.trade import TradeIntent, TradeSource
    from services.trading_service import trading_application
    try:
        if not json.loads(payload).get('intent_id'):
            raise ValueError('MCP requests require a stable intent_id')
        intent=TradeIntent.model_validate_json(payload).model_copy(update={'source':TradeSource.MCP})
        service=trading_application(api_token,source='mcp')
        service.create_trade_intent(intent)
        order=await service.validate_trade(intent.intent_id)
        return ok_response('create_trade_intent',{'intent':intent.model_dump(mode='json'),'order':order.model_dump(mode='json')})
    except Exception as exc:
        return error_response('create_trade_intent',exc)


@mcp.tool()
async def get_order_status(api_token: str, order_id: str, refresh: bool = False) -> str:
    """Read persisted order state for the authenticated account."""
    from services.trading_service import trading_application
    try:
        service=trading_application(api_token,source='mcp')
        account=await service.adapter.get_account()
        order=service.get_order_status(order_id)
        if order.account_id != account.account_id:
            raise PermissionError('Account mismatch')
        if refresh:
            order=await service.refresh_order(order_id)
        return ok_response('get_order_status',{'order':order.model_dump(mode='json')})
    except Exception as exc:
        return error_response('get_order_status',exc)


@mcp.tool()
async def get_trade_intent(api_token: str, intent_id: str) -> str:
    """Read an intent after binding it to the authenticated account."""
    from services.trading_service import trading_application
    try:
        service=trading_application(api_token,source='mcp')
        order=await service.validate_trade(intent_id)
        return ok_response('get_trade_intent',{'intent':service.repo.intent(intent_id).model_dump(mode='json'),
                                             'order':order.model_dump(mode='json')})
    except Exception as exc:
        return error_response('get_trade_intent',exc)


@mcp.tool()
async def check_account_status(api_token: str) -> str:
    try:
        params=AccountStatusInput.model_validate({'api_token':api_token})
        adapter=read_adapter(params.api_token)
        account=await adapter.get_account()
        contracts=[{'contract_id':row.contract_id,'symbol':row.symbol,'contract_type':row.direction,
                    'buy_price':float(row.buy_price)} for row in account.contracts]
        total=sum(row.buy_price for row in account.contracts)
        return ok_response('check_account_status',{'loginid':account.account_id,'account_type':account.mode.value,
            'currency':account.currency,'cash_balance':float(account.balance),'net_equity_estimate':float(account.balance+total),
            'portfolio':{'open_contract_count':len(contracts),'total_open_buy_price':float(total),'contracts':contracts},
            'api_token':mask_secret(params.api_token)})
    except Exception as exc:
        return error_response('check_account_status',exc)


@mcp.tool()
async def get_open_contract_status(api_token: str, contract_id: int | None = None) -> str:
    try:
        params=OpenContractStatusInput.model_validate({'api_token':api_token,'contract_id':contract_id})
        adapter=read_adapter(params.api_token)
        account=await adapter.get_account()
        if params.contract_id:
            contract=(await adapter.get_contract(params.contract_id)).raw
        else:
            contract={'contracts':[{'contract_id':row.contract_id,'symbol':row.symbol,'buy_price':float(row.buy_price)} for row in account.contracts]}
        return ok_response('get_open_contract_status',{'loginid':account.account_id,'account_type':account.mode.value,
            'contract':contract,'api_token':mask_secret(params.api_token)})
    except Exception as exc:
        return error_response('get_open_contract_status',exc)


@mcp.tool()
async def close_open_contract(api_token: str, contract_id: int, price: float = 0.0,
                              allow_live: bool = False, intent_id: str | None = None) -> str:
    """Close only an existing approved SELL intent through TradingService."""
    from services.trading_service import trading_application
    try:
        params=CloseContractInput.model_validate(dict(api_token=api_token,contract_id=contract_id,price=price,allow_live=allow_live))
        if not intent_id:
            raise ValueError('An approved SELL intent_id is required')
        if params.price != 0:
            raise ValueError('Only the approved market-close price (0) is supported')
        service=trading_application(params.api_token,source='mcp')
        intent=service.repo.intent(intent_id)
        if intent.action != 'SELL' or intent.contract_id != params.contract_id:
            raise ValueError('Close parameters do not match the approved intent')
        return order_response('close_open_contract',await service.close_trade(intent_id))
    except Exception as exc:
        return error_response('close_open_contract',exc)


if __name__ == "__main__":
    from services.startup import recover_incomplete_orders
    asyncio.run(recover_incomplete_orders())
    mcp.run()
