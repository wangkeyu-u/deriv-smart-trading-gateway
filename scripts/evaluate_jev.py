#!/usr/bin/env python3
"""Offline labelled policy replay by default; --live calls Jev on artificial fixtures."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from advisory_policy import build_state, decide
from evals.scenarios import CASES, snapshot
from evals.metrics import summarize, rule_baseline
from jev_router import JEV_MODEL, MarketAssessment, assess_market


def evaluate(live=False, key='offline-fixture', model=JEV_MODEL):
    records=[]
    variants={name:[] for name in ('Jev','rules','always_finish','always_deep')}
    for case in CASES:
        state=build_state(case['question'],case['symbol'],snapshot(case['symbol'],quality=case.get('quality','ready')),
                          [],case['scene'],case.get('thesis',''),10)
        if not state['evidence']['tick_current']:
            assessment=MarketAssessment(None,'no_current_tick')
        elif live:
            assessment=assess_market(state,key,model=model,deadline_at=time.monotonic()+2)
        else:
            with patch('jev_router._request',return_value=case['reply']):
                assessment=assess_market(state,key,model=model,deadline_at=time.monotonic()+2)
        decision=decide(state,assessment,'UP',enabled=True)
        actual=[decision['observed_trend'],decision['requested_path']]
        records.append({'id':case['id'],'expected':case['expect'],'actual':actual,
                        'matched':actual==case['expect'],'assessment':assessment.as_dict(),'reason':decision['reason']})
        routes={'Jev':decision['requested_path'],'rules':rule_baseline(state),'always_finish':'finish','always_deep':'deep'}
        for name,path in routes.items():
            if state['evidence']['status']!='ready': path='wait'
            variants[name].append({'path':path,'expected_path':case['expect'][1],
                'failed':name=='Jev' and assessment.source=='jev_error',
                'called':assessment.source in {'jev','jev_error'} if name=='Jev' else True,
                'latency_ms':assessment.latency_ms if name=='Jev' and assessment.source in {'jev','jev_error'} else None,
                'usage':assessment.usage if name=='Jev' else {}})
    comparison={name:summarize(rows,live=live) for name,rows in variants.items()}
    for name in ('rules','always_finish','always_deep'):
        comparison[name]['token_usage']={'input_tokens':0,'output_tokens':0}
        comparison[name]['cost']=0
    return {'mode':'live_model_fixture_eval' if live else 'offline_policy_replay',
        'meaning':'Small artificial labelled set; all variants share evidence guards. Offline Jev uses mocked answers, not measured model quality/latency/cost.',
        'threshold_status':'UNCALIBRATED_THRESHOLD','thresholds':{'probability':.8,'confidence':.7},
        'matched':sum(r['matched'] for r in records),'total':len(records),
        'network_latency_ms':{'p50':comparison['Jev']['latency_p50'],'p95':comparison['Jev']['latency_p95']} if live else None,
        'comparison':comparison,'cases':records}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--model',default=JEV_MODEL)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--input-price-per-million',type=float)
    parser.add_argument('--output-price-per-million',type=float)
    args=parser.parse_args()
    key=os.getenv('TYPESAFE_API_KEY','') if args.live else 'offline-fixture'
    if args.live and not key: parser.error('--live requires TYPESAFE_API_KEY')
    if any(v is not None and (v<0 or not __import__('math').isfinite(v)) for v in (args.input_price_per_million,args.output_price_per_million)):
        parser.error('Prices must be finite and nonnegative')
    report=evaluate(args.live,key,args.model)
    if args.live and args.input_price_per_million is not None and args.output_price_per_million is not None:
        usage=report['comparison']['Jev']['token_usage']
        if usage is not None:
            report['comparison']['Jev']['cost']={'estimated_usd':(usage['input_tokens']*args.input_price_per_million+usage['output_tokens']*args.output_price_per_million)/1e6,
            'basis':'User supplied token prices; not a verified invoice'}
    encoded=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(encoded+'\n')
    print(encoded)
    return 0 if report['matched']==report['total'] else 1


if __name__=='__main__': raise SystemExit(main())
