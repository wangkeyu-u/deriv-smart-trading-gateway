"""Deterministic evidence checks. These aren't independent model agents or votes."""
from domain.market import EvidenceCheck
from advisory_policy import market_evidence, instrument_profile, relevant_news


def build_evidence_checks(market, symbol, sources=()):
    evidence=market_evidence(market,symbol)
    tick=market.get('tick') or {}
    candle_symbol=((market.get('candles') or {}).get('data') or {}).get('symbol')
    symbols_match=all(value in {None,symbol} for value in (tick.get('symbol'),candle_symbol,market.get('symbol')))
    return (
        EvidenceCheck(name='freshness',status='PASS' if evidence['tick_current'] else 'FAIL',reason=evidence['status']),
        EvidenceCheck(name='continuity',status='PASS' if evidence['candles_current'] else 'FAIL',reason=evidence['status']),
        EvidenceCheck(name='symbol',status='PASS' if symbols_match else 'FAIL'),
        EvidenceCheck(name='trend',status=evidence['trend'],reason='Past window only, not a strategy signal'),
        EvidenceCheck(name='counter_case',status='REVIEW',reason='Correlated observations do not establish predictive edge'),
        EvidenceCheck(name='news_context',status='CONTEXT_ONLY' if relevant_news(list(sources),symbol) else 'NOT_APPLICABLE' if not instrument_profile(symbol)['news_applicable'] else 'NO_FRESH_NEWS'),
    )
