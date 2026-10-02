from decimal import Decimal
from enum import StrEnum
from typing import Any
from pydantic import Field
from domain.trade import DomainModel


class TradingState(StrEnum):
    ENABLED='ENABLED'
    REDUCE_ONLY='REDUCE_ONLY'
    HALTED='HALTED'


class RiskResult(DomainModel):
    allowed: bool
    code: str
    reason: str
    metrics: dict[str, Any] = Field(default_factory=dict)


class RiskSnapshot(DomainModel):
    balance: Decimal
    open_stake: Decimal
    open_contracts: int
    symbol_exposure: Decimal
    daily_loss: Decimal
    consecutive_losses: int
    seconds_since_loss: float | None
    orders_last_minute: int
    unresolved_order_count: int
