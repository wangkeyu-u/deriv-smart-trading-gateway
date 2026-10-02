from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from domain.trade import TradingMode


@dataclass(frozen=True)
class OpenPosition:
    contract_id: int
    symbol: str
    buy_price: Decimal
    direction: str | None = None


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    mode: TradingMode
    balance: Decimal
    currency: str
    contracts: tuple[OpenPosition,...] = ()


@dataclass(frozen=True)
class ClosedContract:
    contract_id: int
    buy_price: Decimal
    sell_price: Decimal
    sell_time: float


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    ask_price: Decimal


@dataclass(frozen=True)
class ContractSnapshot:
    contract_id: int
    is_sold: bool
    is_expired: bool
    raw: dict[str, Any] = field(default_factory=dict,repr=False)


@dataclass(frozen=True)
class ReconciliationResult:
    verified: bool
    status: str | None = None
    receipt: dict[str,Any] = field(default_factory=dict)
