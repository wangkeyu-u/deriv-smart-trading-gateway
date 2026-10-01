from typing import Protocol
from domain.market import MarketSnapshot
from domain.trade import TradeSignal

StrategySignal = TradeSignal


class Strategy(Protocol):
    def evaluate(self, snapshot: MarketSnapshot) -> StrategySignal: ...
