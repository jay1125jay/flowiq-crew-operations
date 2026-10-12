#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PERF=ROOT/'data'/'model_state'/'sports_top3_performance.json'
OUT=ROOT/'data'/'model_state'/'sports_top3_calibration.json'
KST=timezone(timedelta(hours=9))
SPORTS=('SOCCER','BASEBALL','BASKETBALL','VOLLEYBALL')
VERSION='SPORTS_TOP3_CALIBRATION_V1_OOS_TIGHTEN_ONLY'
BASE_P={'SOCCER':0.58,'BASEBALL':0.62,'BASKETBALL':0.70,'VOLLEYBALL':0.70}
BASE_M={'SOCCER':0.12,'BASEBALL':0.15,'BASKETBALL':0.20,'VOLLEYBALL':0.20}
MIN_EVAL=30
MIN_SELECTED=20
MIN_COVERAGE=0.35


def _f(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception:return None


def _wilson(h,n,z=1.96):
    if n<=0:return (None,None)
    p=h/n; z2=z*z; d=1+z2/n
    c=(p+z2/(2*n))/d; q=z*math.sqrt((p*(1-p)+z2/(4*n))/n)/d
    return max(0,c-q),min(1,c+q)


def _rows(perf,sport):
    out=[]
    for r in (perf.get('records') or {}).values():
        if r.get('sport')!=sport:continue
        ev=r.get('evaluation') or {}
        if not isinstance(ev.get('hit'),bool):continue
        g=r.get('precision_gate') or {}
        p=_f(g.get('top_p')); m=_f(g.get('margin'))
        if p is None or m is None:continue
        out.append({'p':p,'m':m,'hit':ev['hit'],'at':str(ev.get('evaluated_at') or r.get('recorded_at') or '')})
    out.sort(key=lambda x:x['at'])
    return out


def _grid(base,values,step):
    vals={round(base,4)}
    for v in values:
        if v>=base: vals.add(round(math.floor(v/step)*step,4))
    return sorted(vals)


def calibrate_sport(rows,sport):
    n=len(rows); base_p=BASE_P[sport]; base_m=BASE_M[sport]
    if n<MIN_EVAL:
        return {'state':'HOLD_SAMPLE','evaluated':n,'required':MIN_EVAL,'effective_min_top_p':base_p,'effective_min_margin':base_m,'source':'BASE_HEURISTIC_FLOOR'}
    candidates=[]
    pgrid=_grid(base_p,[x['p'] for x in rows],0.02)
    mgrid=_grid(base_m,[x['m'] for x in rows],0.04)
    for p in pgrid:
        for m in mgrid:
            sel=[x for x in rows if x['p']>=p and x['m']>=m]
            sn=len(sel); cov=sn/n
            if sn<MIN_SELECTED or cov<MIN_COVERAGE:continue
            h=sum(1 for x in sel if x['hit']); lo,hi=_wilson(h,sn)
            candidates.append({'min_top_p':p,'min_margin':m,'selected':sn,'coverage':cov,'hits':h,'hit_rate':h/sn,'wilson95_lower':lo,'wilson95_upper':hi})
    if not candidates:
        return {'state':'HOLD_INSUFFICIENT_COVERAGE','evaluated':n,'required_selected':MIN_SELECTED,'min_coverage':MIN_COVERAGE,'effective_min_top_p':base_p,'effective_min_margin':base_m,'source':'BASE_HEURISTIC_FLOOR'}
    # Precision-first but evidence-aware: maximize Wilson lower bound, then N, then hit rate.
    best=max(candidates,key=lambda x:(x['wilson95_lower'],x['selected'],x['hit_rate']))
    base=next((x for x in candidates if abs(x['min_top_p']-base_p)<1e-9 and abs(x['min_margin']-base_m)<1e-9),None)
    # Never loosen below the original floor; require a meaningful lower-bound gain to tighten.
    gain=(best['wilson95_lower']-(base or best)['wilson95_lower']) if base else 0.0
    activate=(best['min_top_p']>base_p or best['min_margin']>base_m) and gain>=0.02
    ep=best['min_top_p'] if activate else base_p; em=best['min_margin'] if activate else base_m
    return {
        'state':'CALIBRATED_TIGHTENED' if activate else 'CALIBRATED_KEEP_BASE',
        'evaluated':n,'effective_min_top_p':round(ep,4),'effective_min_margin':round(em,4),
        'source':'LIVE_LOCKED_OOS_RESULTS','tighten_only':True,'min_selected':MIN_SELECTED,'min_coverage':MIN_COVERAGE,
        'best':{k:(round(v,6) if isinstance(v,float) else v) for k,v in best.items()},
        'base':({k:(round(v,6) if isinstance(v,float) else v) for k,v in base.items()} if base else None),
        'wilson_lower_gain':round(gain,6),'candidate_grid_size':len(candidates)
    }


def build(perf,now=None):
    now=now or datetime.now(KST)
    return {'version':VERSION,'generated_at':now.isoformat(timespec='seconds'),'by_sport':{s:calibrate_sport(_rows(perf,s),s) for s in SPORTS},'policy':'TRUE_OOS_SOURCE=LOCKED_LIVE_PICKS_RESOLVED_AFTER_EVENT; MIN_30_EVALUATED; MIN_20_SELECTED; MIN_35PCT_COVERAGE; OPTIMIZE_WILSON95_LOWER; REQUIRE_2PCT_LOWER_BOUND_GAIN_TO_TIGHTEN; NEVER_RELAX_BELOW_BASE; NO_FUTURE_RESULT_LEAKAGE'}


def run(perf_path=PERF,out_path=OUT):
    perf=json.loads(Path(perf_path).read_text(encoding='utf-8')) if Path(perf_path).exists() else {}
    out=build(perf); out_path.parent.mkdir(parents=True,exist_ok=True); out_path.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'SPORTS_TOP3_CALIBRATION':'PASS','states':{s:v['state'] for s,v in out['by_sport'].items()}},ensure_ascii=False))


def self_test():
    perf={'records':{}}
    # 40 genuine resolved observations; high-confidence slice performs better.
    for i in range(40):
        high=i>=20; p=.82 if high else .71; m=.42 if high else .22
        hit=(i%10!=0) if high else (i%2==0)
        perf['records'][str(i)]={'sport':'BASKETBALL','precision_gate':{'top_p':p,'margin':m},'evaluation':{'hit':hit,'evaluated_at':f'2026-10-{1+i//4:02d}T12:00:00+09:00'}}
    out=build(perf,datetime(2026,10,12,12,0,tzinfo=KST))
    b=out['by_sport']['BASKETBALL']
    assert b['state']=='CALIBRATED_TIGHTENED',b
    assert b['effective_min_top_p']>=BASE_P['BASKETBALL'] and b['effective_min_margin']>=BASE_M['BASKETBALL']
    assert out['by_sport']['SOCCER']['state']=='HOLD_SAMPLE'
    print('SPORTS_TOP3_CALIBRATION_SELF_TEST=PASS')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');a=ap.parse_args(); self_test() if a.self_test else run()
if __name__=='__main__':main()
