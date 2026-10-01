"""Routing comparisons on labelled read-only scenarios, never trading returns."""
import math
import statistics


def rule_baseline(state):
    if state['evidence']['status']!='ready':
        return 'wait'
    if state['scene'] in {'review','research'} or any(word in state['question'].lower() for word in ('why','explain','assumption','为什么','解释','假设')):
        return 'deep'
    return 'finish'


def summarize(records, *, live=False):
    n=len(records)
    expected=[r['expected_path'] for r in records]
    actual=[r['path'] for r in records]
    deep_required=sum(p=='deep' for p in expected)
    not_deep=n-deep_required
    calls=[row for row in records if row.get('called',True)]
    measured=[row for row in calls if {'input_tokens','output_tokens'}<=set(row.get('usage',{}))]
    latency=sorted(r['latency_ms'] for r in records if r.get('latency_ms') is not None)
    return {'routing_accuracy':sum(a==b for a,b in zip(expected,actual))/n if n else None,
        'WAIT_accuracy':sum((a=='wait')==(b=='wait') for a,b in zip(expected,actual))/n if n else None,
        'unnecessary_deep_rate':sum(a!='deep' and b=='deep' for a,b in zip(expected,actual))/not_deep if not_deep else None,
        'missed_deep_rate':sum(a=='deep' and b!='deep' for a,b in zip(expected,actual))/deep_required if deep_required else None,
        'failure_rate':sum(bool(r.get('failed')) for r in calls)/len(calls) if calls else None,
        'latency_p50':statistics.median(latency) if live and latency else None,
        'latency_p95':latency[math.ceil(.95*len(latency))-1] if live and latency else None,
        'token_usage':{'input_tokens':sum(r.get('usage',{}).get('input_tokens',0) for r in measured),
                       'output_tokens':sum(r.get('usage',{}).get('output_tokens',0) for r in measured)} if live and calls and len(measured)==len(calls) else None,
        'usage_coverage':len(measured)/len(calls) if live and calls else None,
        'cost':None}
