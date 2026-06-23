"""Deriv Smart Trading Gateway MCP server.

This server exposes a small, strictly typed FastMCP tool surface for reading
Deriv market data and executing token-authenticated demo/live contract buys.
Use demo Deriv tokens for simulated trading workflows.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal

import pandas as pd
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from typing_extensions import Annotated
from websockets.exceptions import ConnectionClosed, WebSocketException

from deriv_client import (  # type: ignore[import-not-found]
    DerivWebSocketClient,
    DerivAPIError,
    DerivTimeoutError,
    GatewayError,
    account_type_from_authorize,
    clean_json,
    enforce_demo_or_explicit_live,
    error_response,
    extract_tick,
    mask_secret,
    normalize_candles,
    ok_response,
    summarize_portfolio,
    utc_now_iso,
)


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


class SimulatedTradeInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    api_token: NonEmptyString
    symbol: NonEmptyString
    amount: Annotated[float, Field(gt=0)]
    contract_type: ContractType
    duration: Annotated[int, Field(ge=1)]
    duration_unit: DurationUnit
    allow_live: bool = False


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


@mcp.tool()
async def get_market_ticks(symbol: str, subscribe: bool = False) -> str:
    """Fetch the latest Deriv tick for a symbol, optionally sampling a live stream."""
    tool = "get_market_ticks"
    try:
        params = MarketTicksInput.model_validate({"symbol": symbol, "subscribe": subscribe})
        async with DerivWebSocketClient() as client:
            payload: dict[str, Any] = {"ticks": params.symbol}
            if params.subscribe:
                payload["subscribe"] = 1

            first_response = await client.request(payload)
            first_tick = extract_tick(first_response)
            subscription_id = (first_response.get("subscription") or {}).get("id")
            stream_ticks: list[dict[str, Any]] = []

            if params.subscribe and subscription_id:
                stream_messages = await client.collect_subscription(subscription_id)
                stream_ticks = [extract_tick(message) for message in stream_messages]

            return ok_response(
                tool,
                {
                    "symbol": params.symbol,
                    "subscribe": params.subscribe,
                    "subscription_id": subscription_id,
                    "tick": first_tick,
                    "stream_sample": stream_ticks,
                    "stream_sample_limit": SUBSCRIPTION_SAMPLE_SIZE,
                    "timeout_seconds": REQUEST_TIMEOUT_SECONDS,
                },
            )
    except Exception as exc:
        return error_response(tool, exc)


@mcp.tool()
async def get_historical_candles(symbol: str, granularity: int, count: int) -> str:
    """Fetch Deriv historical candles in normalized OHLCV format."""
    tool = "get_historical_candles"
    try:
        params = HistoricalCandlesInput.model_validate(
            {"symbol": symbol, "granularity": granularity, "count": count}
        )
        async with DerivWebSocketClient() as client:
            response = await client.request(
                {
                    "ticks_history": params.symbol,
                    "adjust_start_time": 1,
                    "count": params.count,
                    "end": "latest",
                    "granularity": params.granularity,
                    "style": "candles",
                }
            )
            candles = normalize_candles(response)
            return ok_response(
                tool,
                {
                    "symbol": params.symbol,
                    "granularity": params.granularity,
                    "requested_count": params.count,
                    "returned_count": len(candles),
                    "ohlcv": candles,
                },
            )
    except Exception as exc:
        return error_response(tool, exc)


@mcp.tool()
async def execute_simulated_trade(
    api_token: str,
    symbol: str,
    amount: float,
    contract_type: str,
    duration: int,
    duration_unit: str,
    allow_live: bool = False,
) -> str:
    """Authorize and buy a Deriv CALL/PUT contract, returning an immutable receipt."""
    tool = "execute_simulated_trade"
    try:
        params = SimulatedTradeInput.model_validate(
            {
                "api_token": api_token,
                "symbol": symbol,
                "amount": amount,
                "contract_type": contract_type,
                "duration": duration,
                "duration_unit": duration_unit,
                "allow_live": allow_live,
            }
        )

        async with DerivWebSocketClient(api_token=params.api_token) as client:
            authorize = client.authorization or {}
            account_type = enforce_demo_or_explicit_live(authorize, params.allow_live)
            currency = authorize.get("currency")

            proposal_response = await client.request(
                {
                    "proposal": 1,
                    "amount": params.amount,
                    "basis": "stake",
                    "contract_type": params.contract_type,
                    "currency": currency,
                    "duration": params.duration,
                    "duration_unit": params.duration_unit,
                    "symbol": params.symbol,
                }
            )
            proposal = proposal_response.get("proposal") or {}
            proposal_id = proposal.get("id")
            ask_price = proposal.get("ask_price")

            if not proposal_id or ask_price is None:
                raise DerivAPIError("Deriv proposal response did not include id and ask_price")

            buy_response = await client.request(
                {"buy": proposal_id, "price": ask_price},
                retries=0,
            )
            buy = buy_response.get("buy") or {}

            receipt = {
                "contract_id": buy.get("contract_id"),
                "transaction_id": buy.get("transaction_id"),
                "purchase_price": buy.get("buy_price") or buy.get("purchase_price") or ask_price,
                "currency": currency,
                "symbol": params.symbol,
                "amount": params.amount,
                "contract_type": params.contract_type,
                "duration": params.duration,
                "duration_unit": params.duration_unit,
                "proposal_id": proposal_id,
                "longcode": buy.get("longcode") or proposal.get("longcode"),
                "account_type": account_type,
                "loginid": authorize.get("loginid"),
                "api_token": mask_secret(params.api_token),
                "note": "Use a Deriv demo token for simulated trading workflows.",
            }
            return ok_response(tool, {"receipt": receipt})
    except Exception as exc:
        return error_response(tool, exc)


@mcp.tool()
async def check_account_status(api_token: str) -> str:
    """Authorize and return balance plus open-contract portfolio metrics."""
    tool = "check_account_status"
    try:
        params = AccountStatusInput.model_validate({"api_token": api_token})
        async with DerivWebSocketClient(api_token=params.api_token) as client:
            authorize = client.authorization or {}
            balance_response = await client.request({"balance": 1, "subscribe": 0})
            portfolio_response = await client.request({"portfolio": 1})

            balance = balance_response.get("balance") or {}
            portfolio = summarize_portfolio(portfolio_response)
            cash_balance = float(balance.get("balance") or 0)

            return ok_response(
                tool,
                {
                    "loginid": balance.get("loginid"),
                    "account_type": account_type_from_authorize(authorize),
                    "currency": balance.get("currency"),
                    "cash_balance": cash_balance,
                    "net_equity_estimate": cash_balance + portfolio["total_open_buy_price"],
                    "portfolio": portfolio,
                    "api_token": mask_secret(params.api_token),
                },
            )
    except Exception as exc:
        return error_response(tool, exc)


@mcp.tool()
async def get_open_contract_status(api_token: str, contract_id: int | None = None) -> str:
    """Authorize and fetch latest status for one open contract or all open contracts."""
    tool = "get_open_contract_status"
    try:
        params = OpenContractStatusInput.model_validate(
            {"api_token": api_token, "contract_id": contract_id}
        )
        async with DerivWebSocketClient(api_token=params.api_token) as client:
            authorize = client.authorization or {}
            payload: dict[str, Any] = {"proposal_open_contract": 1}
            if params.contract_id:
                payload["contract_id"] = params.contract_id
            response = await client.request(payload)
            contract = response.get("proposal_open_contract") or {}
            return ok_response(
                tool,
                {
                    "account_type": account_type_from_authorize(authorize),
                    "loginid": authorize.get("loginid"),
                    "contract": contract,
                    "api_token": mask_secret(params.api_token),
                },
            )
    except Exception as exc:
        return error_response(tool, exc)


@mcp.tool()
async def close_open_contract(
    api_token: str,
    contract_id: int,
    price: float = 0.0,
    allow_live: bool = False,
) -> str:
    """Authorize and sell an open contract by contract_id. price=0 means sell at market."""
    tool = "close_open_contract"
    try:
        params = CloseContractInput.model_validate(
            {
                "api_token": api_token,
                "contract_id": contract_id,
                "price": price,
                "allow_live": allow_live,
            }
        )
        async with DerivWebSocketClient(api_token=params.api_token) as client:
            authorize = client.authorization or {}
            account_type = enforce_demo_or_explicit_live(authorize, params.allow_live)
            response = await client.request(
                {"sell": params.contract_id, "price": params.price},
                retries=0,
            )
            sell = response.get("sell") or {}
            return ok_response(
                tool,
                {
                    "account_type": account_type,
                    "loginid": authorize.get("loginid"),
                    "contract_id": params.contract_id,
                    "sell": sell,
                    "api_token": mask_secret(params.api_token),
                },
            )
    except Exception as exc:
        return error_response(tool, exc)


if __name__ == "__main__":
    mcp.run()
