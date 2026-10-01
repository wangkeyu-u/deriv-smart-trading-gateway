"""Pure deterministic policy: no network, SQLite, session state or model output."""
from domain.risk import RiskResult, RiskSnapshot, TradingState


class RiskEngine:
    def evaluate(self, intent, snapshot: RiskSnapshot, policy, state=TradingState.ENABLED):
        metrics=snapshot.model_dump(mode='json')
        def result(allowed,code,reason): return RiskResult(allowed=allowed,code=code,reason=reason,metrics=metrics)
        if intent.action=='SELL':
            return result(True,'REDUCING_EXPOSURE','Approved close remains available')
        conditions=[
            (state==TradingState.HALTED,'TRADING_HALTED','New buys are halted'),
            (state==TradingState.REDUCE_ONLY,'REDUCE_ONLY','Only position reduction is enabled'),
            (snapshot.unresolved_order_count>0,'UNRESOLVED_ORDER','Resolve uncertain writes before another buy'),
            (intent.symbol not in policy.allowed_symbols,'SYMBOL_NOT_ALLOWED','Symbol is not allowed'),
            (intent.direction.value not in policy.allowed_contract_types,'CONTRACT_NOT_ALLOWED','Contract type is not allowed'),
            (intent.amount>policy.max_stake_per_trade,'MAX_STAKE_PER_TRADE','Stake limit exceeded'),
            (snapshot.open_stake+intent.amount>policy.max_total_open_stake,'MAX_TOTAL_OPEN_STAKE','Total exposure limit exceeded'),
            (snapshot.open_contracts>=policy.max_open_contracts,'MAX_OPEN_CONTRACTS','Open contract limit reached'),
            (snapshot.symbol_exposure+intent.amount>policy.max_symbol_exposure,'MAX_SYMBOL_EXPOSURE','Symbol exposure limit exceeded'),
            (snapshot.daily_loss>=policy.max_daily_loss,'MAX_DAILY_LOSS','Realized UTC daily loss limit reached'),
            (snapshot.consecutive_losses>=policy.max_consecutive_losses,'MAX_CONSECUTIVE_LOSSES','Consecutive loss limit reached'),
            (snapshot.seconds_since_loss is not None and snapshot.seconds_since_loss<policy.cooldown_after_loss,'LOSS_COOLDOWN','Loss cooldown is active'),
            (snapshot.balance-intent.amount<policy.min_available_balance,'MIN_AVAILABLE_BALANCE','Conservative available balance floor exceeded'),
            ((intent.duration if intent.duration_unit=='t' else intent.duration*(3600 if intent.duration_unit=='h' else 60))>(policy.max_tick_duration if intent.duration_unit=='t' else policy.max_duration),'MAX_DURATION','Duration limit exceeded'),
            (snapshot.orders_last_minute>=policy.max_orders_per_minute,'MAX_ORDER_RATE','Submission rate limit reached'),
        ]
        for blocked,code,reason in conditions:
            if blocked: return result(False,code,reason)
        return result(True,'ALLOWED','Deterministic limits passed')
