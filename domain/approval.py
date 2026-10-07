from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from pydantic import Field

from domain.trade import DomainModel, Direction, TradingMode, utc_now


class Approval(DomainModel):
    approval_id: str = Field(default_factory=lambda: str(uuid4()))
    intent_id: str
    account_id: str
    symbol: str
    direction: Direction | None
    amount: Decimal
    duration: int
    duration_unit: str
    account_mode: TradingMode
    contract_id: int | None
    fingerprint: str
    approved_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    approved_by: str
