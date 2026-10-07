from enum import StrEnum

from domain.trade import DomainModel


class ObservedTrend(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"
    UNKNOWN = "UNKNOWN"


class EvidenceCheck(DomainModel):
    name: str
    status: str
    reason: str = ""


def legacy_observation(value: str | None) -> ObservedTrend:
    """Only for reading old histories / migrating a user's saved review input."""
    return {"CALL": ObservedTrend.UP, "PUT": ObservedTrend.DOWN, "up": ObservedTrend.UP,
            "down": ObservedTrend.DOWN, "mixed": ObservedTrend.FLAT}.get(value, ObservedTrend.UNKNOWN)

from datetime import datetime
from decimal import Decimal
from pydantic import Field


class MarketSnapshot(DomainModel):
    symbol: str
    quote: Decimal | None
    observed_at: datetime
    observed_trend: ObservedTrend = ObservedTrend.UNKNOWN
    evidence_checks: tuple[EvidenceCheck,...] = ()
