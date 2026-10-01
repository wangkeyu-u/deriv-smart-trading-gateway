from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DomainModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, allow_inf_nan=False)


class TradeAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class Direction(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


class TradingMode(StrEnum):
    DEMO = "demo"
    LIVE = "live"


class TradeSource(StrEnum):
    STREAMLIT = "streamlit"
    MCP = "mcp"
    MANAGER = "manager"


class TradeIntentDraft(DomainModel):
    action: TradeAction
    symbol: str = Field(min_length=1, max_length=64)
    direction: Direction | None = None
    amount: Decimal = Field(ge=0, decimal_places=2)
    duration: int = Field(ge=0)
    duration_unit: str = Field(pattern=r"^[mht]$")
    contract_id: int | None = Field(default=None, gt=0)

    @field_validator('symbol')
    @classmethod
    def normalized_symbol(cls,value):
        value=value.strip()
        if not value or any(c.isspace() for c in value):
            raise ValueError('Symbol must be a nonempty broker identifier')
        return value

    @field_validator("action", "direction", mode="before")
    @classmethod
    def enum_values(cls, value, info):
        if value is None:
            return None
        return (TradeAction if info.field_name == "action" else Direction)(value)

    @model_validator(mode="after")
    def action_fields(self):
        if self.action == TradeAction.BUY:
            if self.direction is None or self.amount <= 0 or self.duration <= 0 or self.contract_id is not None:
                raise ValueError("BUY requires direction, positive stake/duration and no contract_id")
        elif self.contract_id is None or self.direction is not None:
            raise ValueError("SELL requires contract_id and no directional signal")
        return self


class TradeIntent(TradeIntentDraft):
    intent_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128)
    account_mode: TradingMode
    source: TradeSource
    request_id: str = ""
    correlation_id: str = ""
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("account_mode", "source", mode="before")
    @classmethod
    def enum_values_extra(cls, value, info):
        return (TradingMode if info.field_name == "account_mode" else TradeSource)(value)

    @field_validator("created_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("Business timestamps require a timezone")
        return value.astimezone(timezone.utc)


class TradeSignal(DomainModel):
    strategy_id: str
    symbol: str
    direction: Direction | None  # None means WAIT, never infer from ObservedTrend
    generated_at: datetime
    valid_until: datetime
    reason: str
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def valid_window(self):
        if self.generated_at.tzinfo is None or self.valid_until.tzinfo is None or self.valid_until <= self.generated_at:
            raise ValueError('Signal requires a valid UTC window')
        return self
