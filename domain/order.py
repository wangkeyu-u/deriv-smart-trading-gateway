from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field

from domain.trade import Direction, DomainModel, TradeAction, utc_now


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVED = "APPROVED"
    SUBMITTING = "SUBMITTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    RECONCILING = "RECONCILING"
    CANCELLED = "CANCELLED"


class Order(DomainModel):
    order_id: str = Field(default_factory=lambda: str(uuid4()))
    intent_id: str
    idempotency_key: str
    account_id: str
    action: TradeAction
    status: OrderStatus = OrderStatus.CREATED
    symbol: str
    direction: Direction | None
    amount: Decimal
    contract_id: int | None = None
    transaction_id: int | None = None
    proposal_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    submitted_at: datetime | None = None
    last_error: str | None = None
    receipt: dict[str, Any] = Field(default_factory=dict)
    request_id: str = ""
    correlation_id: str = ""


class OrderEvent(DomainModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    order_id: str
    previous_status: OrderStatus | None
    new_status: OrderStatus
    event_type: str
    timestamp: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)
