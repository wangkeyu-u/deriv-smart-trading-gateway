import os
from pathlib import Path
from decimal import Decimal
from pydantic import Field
from domain.trade import DomainModel


class RiskPolicy(DomainModel):
    max_stake_per_trade: Decimal = Field(default=Decimal('50'), gt=0)
    max_total_open_stake: Decimal = Field(default=Decimal('200'), gt=0)
    max_open_contracts: int = Field(default=5, gt=0)
    max_symbol_exposure: Decimal = Field(default=Decimal('100'), gt=0)
    max_daily_loss: Decimal = Field(default=Decimal('50'), gt=0)
    max_consecutive_losses: int = Field(default=3, gt=0)
    cooldown_after_loss: int = Field(default=60, ge=0)
    min_available_balance: Decimal = Field(default=Decimal('10'), ge=0)
    allowed_symbols: tuple[str,...] = ('R_100','R_75','R_50','R_25','R_10','frxEURUSD','frxGBPUSD')
    allowed_contract_types: tuple[str,...] = ('CALL','PUT')
    max_duration: int = Field(default=3600, gt=0)  # seconds for m/h
    max_tick_duration: int = Field(default=10, gt=0)
    max_orders_per_minute: int = Field(default=5, gt=0)

    @classmethod
    def configured(cls):
        path=os.getenv('DERIV_RISK_POLICY')
        return cls.model_validate_json(Path(path).read_text()) if path else cls()
