#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / 'data' / 'model_state' / 'sports_top3_performance.json'
OUT = ROOT / 'data' / 'model_state' / 'sports_top3_circuit.json'
KST = timezone(timedelta(hours=9))
SPORTS = ('SOCCER','BASEBALL','BASKETBALL','VOLLEYBALL')
VERSION = 'SPORTS_TOP3_CIRCUIT_V1'
MIN_EVALUATED = 30
TARGET_HIT_RATE = 0.70
RECENT_WINDOW = 20
SEVERE_RECENT_RATE = 0.50
COOLDOWN_HOURS = 24


def _dt(v):
    if not v: return None
    try:
        x=datetime.fromisoformat(str(v).replace('Z','+00:00'))
        return x if x.tzinfo else x.replace(tzinfo=KST)
    except Exception:
        return None


def _wilson(hits:int,n:int,z:float=1.96):
    if n <= 0: return (None,None)
    p=hits/n; z2=z*z; den=1+z2/n
    center=(p+z2/(2*n))/den
    half=z*math.sqrt((p*(1-p)+z2/(4*n))/n)/den
    return max(0.0,center-half), min(1.0,center+half)


def build(history:dict|None, now:datetime|None=None):
    now=now or datetime.now(KST)
    records=(history or {}).get('records') or {}
    by_sport={}
    for sport in SPORTS:
        all_rows=[r for r in records.values() if r.get('sport')==sport]
        evaluated=[r for r in all_rows if isinstance(r.get('evaluation'),dict) and isinstance(r['evaluation'].get('hit'),bool)]
        evaluated.sort(key=lambda r:str((r.get('evaluation') or {}).get('evaluated_at') or r.get('recorded_at') or ''))
        hits=sum(1 for r in evaluated if r['evaluation']['hit'])
        n=len(evaluated); rate=hits/n if n else None
        lo,hi=_wilson(hits,n)
        recent=evaluated[-RECENT_WINDOW:]
        rh=sum(1 for r in recent if r['evaluation']['hit'])
        rr=rh/len(recent) if recent else None
        pending=sum(1 for r in all_rows if not (isinstance(r.get('evaluation'),dict) and isinstance(r['evaluation'].get('hit'),bool)))
        latest=_dt((evaluated[-1].get('evaluation') or {}).get('evaluated_at')) if evaluated else None
        age_h=(now-latest.astimezone(now.tzinfo)).total_seconds()/3600 if latest else None
        evidence=[]
        if n >= MIN_EVALUATED and hi is not None and hi < TARGET_HIT_RATE:
            evidence.append('WILSON95_UPPER_BELOW_TARGET')
        if n >= MIN_EVALUATED and len(recent) >= RECENT_WINDOW and rr is not None and rr < SEVERE_RECENT_RATE:
            evidence.append('RECENT20_BELOW_50PCT')
        if n < MIN_EVALUATED:
            state='LEARNING'; allow_new=3
        elif not evidence:
            state='ACTIVE'; allow_new=3
        elif age_h is not None and age_h < COOLDOWN_HOURS:
            state='BLOCK_24H'; allow_new=0
        elif pending > 0:
            state='BLOCK_PENDING_PROBE'; allow_new=0
        else:
            state='PROBATION_ONE_PICK'; allow_new=1
        by_sport[sport]={
            'state':state,'allow_new_picks':allow_new,'evaluated':n,'pending':pending,'hits':hits,
            'hit_rate':round(rate,6) if rate is not None else None,
            'wilson95_lower':round(lo,6) if lo is not None else None,
            'wilson95_upper':round(hi,6) if hi is not None else None,
            'recent_n':len(recent),'recent_hit_rate':round(rr,6) if rr is not None else None,
            'evidence':evidence,'latest_evaluated_at':latest.isoformat(timespec='seconds') if latest else None,
            'cooldown_hours':COOLDOWN_HOURS,
        }
    return {
        'version':VERSION,'generated_at':now.isoformat(timespec='seconds'),'by_sport':by_sport,
        'policy':'NO_AUTO_THRESHOLD_MUTATION; <30=LEARNING; BLOCK_IF_95PCT_WILSON_UPPER_BELOW_70PCT_OR_RECENT20_BELOW_50PCT; 24H_COOLDOWN; THEN_ONE_PICK_PROBATION; PENDING_PROBE_BLOCKS_MORE_PICKS; EXISTING_LOCKED_PICKS_ARE_GRANDFATHERED'
    }


def run(history_path:Path=HISTORY,out_path:Path=OUT):
    history={}
    if history_path.exists():
        try: history=json.loads(history_path.read_text(encoding='utf-8'))
        except Exception: history={}
    out=build(history)
    out_path.parent.mkdir(parents=True,exist_ok=True)
    out_path.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'SPORTS_TOP3_CIRCUIT':'PASS','states':{s:v['state'] for s,v in out['by_sport'].items()}},ensure_ascii=False))


def self_test():
    now=datetime(2026,10,12,12,0,tzinfo=KST)
    rec={}
    for i in range(30):
        rec[f'B{i}']={'sport':'BASKETBALL','recorded_at':now.isoformat(),'evaluation':{'hit':i<10,'evaluated_at':(now-timedelta(hours=1)).isoformat()}}
    out=build({'records':rec},now)
    assert out['by_sport']['BASKETBALL']['state']=='BLOCK_24H'
    assert out['by_sport']['BASKETBALL']['allow_new_picks']==0
    assert out['by_sport']['SOCCER']['state']=='LEARNING'
    old=now-timedelta(hours=30)
    for r in rec.values(): r['evaluation']['evaluated_at']=old.isoformat()
    out=build({'records':rec},now)
    assert out['by_sport']['BASKETBALL']['state']=='PROBATION_ONE_PICK'
    rec['P']={'sport':'BASKETBALL','recorded_at':now.isoformat()}
    out=build({'records':rec},now)
    assert out['by_sport']['BASKETBALL']['state']=='BLOCK_PENDING_PROBE'
    print('SPORTS_TOP3_CIRCUIT_SELF_TEST=PASS')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');a=ap.parse_args()
    self_test() if a.self_test else run()

if __name__=='__main__': main()
