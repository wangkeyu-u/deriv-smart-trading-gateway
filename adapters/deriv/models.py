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


def validate_account_snapshot(account: AccountSnapshot) -> AccountSnapshot:
    """Validate an adapter snapshot before identity binding or exposure arithmetic."""
    if (not isinstance(account, AccountSnapshot)
            or not isinstance(account.account_id, str) or not account.account_id.strip()
            or account.mode not in {TradingMode.DEMO, TradingMode.LIVE}
            or not isinstance(account.currency, str) or not account.currency.strip()):
        raise ValueError('Invalid account identity')
    if (not isinstance(account.balance, Decimal) or not account.balance.is_finite()
            or account.balance < 0):
        raise ValueError('Invalid account balance')
    if not isinstance(account.contracts, tuple):
        raise ValueError('Incomplete account portfolio')
    identities = set()
    for position in account.contracts:
        if (not isinstance(position, OpenPosition) or type(position.contract_id) is not int
                or position.contract_id <= 0):
            raise ValueError('Invalid portfolio contract identity')
        if position.contract_id in identities:
            raise ValueError('Duplicate portfolio contract identity')
        identities.add(position.contract_id)
        if (not isinstance(position.symbol, str) or not position.symbol
                or len(position.symbol) > 64 or any(char.isspace() for char in position.symbol)):
            raise ValueError('Invalid portfolio symbol')
        if (not isinstance(position.buy_price, Decimal) or not position.buy_price.is_finite()
                or position.buy_price < 0):
            raise ValueError('Invalid portfolio buy price')
    return account


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
