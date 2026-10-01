from datetime import timedelta
from decimal import Decimal
import pytest
from pydantic import ValidationError
from domain.market import MarketSnapshot,ObservedTrend
from domain.trade import TradeSignal,utc_now
from evals.metrics import summarize
from scripts.evaluate_jev import evaluate


def test_offline_eval_compares_routes_without_claiming_live_metrics():
    result=evaluate()
    assert result['matched']==result['total']==12
    assert result['threshold_status']=='UNCALIBRATED_THRESHOLD'
    assert set(result['comparison'])=={'Jev','rules','always_finish','always_deep'}
    jev=result['comparison']['Jev']
    assert jev['routing_accuracy']==1 and jev['latency_p50'] is None and jev['cost'] is None
    assert jev['token_usage'] is None


def test_metrics_use_labelled_denominators():
    result=summarize([{'expected_path':'deep','path':'finish'},{'expected_path':'finish','path':'deep'},{'expected_path':'wait','path':'wait'}])
    assert result['routing_accuracy']==1/3 and result['missed_deep_rate']==1
    assert result['unnecessary_deep_rate']==.5 and result['WAIT_accuracy']==1


def test_observation_cannot_be_used_as_trade_signal():
    now=utc_now()
    snapshot=MarketSnapshot(symbol='R_100',quote=Decimal('100'),observed_at=now,observed_trend=ObservedTrend.UP)
    with pytest.raises(ValidationError):
        TradeSignal(strategy_id='example',symbol=snapshot.symbol,direction=snapshot.observed_trend,
                    generated_at=now,valid_until=now+timedelta(seconds=10),reason='observation only')


def test_live_missing_usage_is_unknown_instead_of_zero_cost():
    result=summarize([{'expected_path':'finish','path':'finish','latency_ms':10,'called':True,'usage':{}}],live=True)
    assert result['token_usage'] is None and result['usage_coverage']==0
    assert result['latency_p50']==10 and result['cost'] is None
