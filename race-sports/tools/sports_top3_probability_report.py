#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from datetime import datetime,timedelta,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LEDGER=ROOT/'data'/'model_state'/'sports_top3_candidate_ledger.json'
OUT=ROOT/'data'/'model_state'/'sports_top3_probability_report.json'
SNAPSHOT=ROOT/'data'/'sports_today.json'
KST=timezone(timedelta(hours=9));SPORTS=('SOCCER','BASEBALL','BASKETBALL','VOLLEYBALL')
VERSION='SPORTS_TOP3_PROBABILITY_REPORT_V1_TRUE_OOS_WILSON95'
BINS=((0.0,0.50,'UNDER_50'),(0.50,0.55,'50_55'),(0.55,0.60,'55_60'),(0.60,0.65,'60_65'),(0.65,0.70,'65_70'),(0.70,0.75,'70_75'),(0.75,1.0000001,'75_PLUS'))

def _f(v):
 try:
  x=float(v);return x if math.isfinite(x) else None
 except Exception:return None

def _wilson(h,n,z=1.959963984540054):
 if n<=0:return (None,None)
 p=h/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;m=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/d
 return (max(0,c-m),min(1,c+m))

def _bucket(p):
 for lo,hi,k in BINS:
  if lo<=p<hi:return k
 return '75_PLUS' if p>=.75 else 'UNDER_50'

def _stats(rows):
 ev=[r for r in rows if isinstance((r.get('evaluation') or {}).get('hit'),bool)]
 hits=sum(1 for r in ev if r['evaluation']['hit']);n=len(ev);lo,hi=_wilson(hits,n)
 probs=[_f(r.get('top_p')) for r in ev];probs=[p for p in probs if p is not None]
 mean_p=sum(probs)/len(probs) if probs else None;rate=hits/n if n else None
 return {'observed':len(rows),'evaluated':n,'pending':len(rows)-n,'hits':hits,'misses':n-hits,'hit_rate':round(rate,6) if rate is not None else None,'mean_model_p':round(mean_p,6) if mean_p is not None else None,'calibration_gap':round(rate-mean_p,6) if rate is not None and mean_p is not None else None,'wilson95_lower':round(lo,6) if lo is not None else None,'wilson95_upper':round(hi,6) if hi is not None else None}

def build(ledger,now=None):
 now=now or datetime.now(KST);records=list((ledger.get('records') or {}).values())
 bins={}
 for _,_,k in BINS:bins[k]=_stats([r for r in records if (_f(r.get('top_p')) is not None and _bucket(_f(r.get('top_p')))==k)])
 by={}
 for sport in SPORTS:
  sr=[r for r in records if r.get('sport')==sport];sb={}
  for _,_,k in BINS:sb[k]=_stats([r for r in sr if (_f(r.get('top_p')) is not None and _bucket(_f(r.get('top_p')))==k)])
  by[sport]={'overall':_stats(sr),'bins':sb}
 out={'version':VERSION,'generated_at':now.isoformat(timespec='seconds'),'source_version':ledger.get('version'),'overall':_stats(records),'bins':bins,'by_sport':by,'bin_contract':[{'key':k,'min_inclusive':lo,'max_exclusive':None if hi>1 else hi} for lo,hi,k in BINS],'interpretation':{'primary_precision_metric':'wilson95_lower','calibration_gap':'hit_rate_minus_mean_model_probability','minimum_evaluated_for_directional_read':30,'state':'HOLD_SAMPLE' if _stats(records)['evaluated']<30 else 'READABLE'},'policy':'TRUE_OOS_FIRST_PRE_EVENT_PREDICTIONS_ONLY; FINAL_RESULTS_ONLY; NO_TOP3_SELECTION_FILTER; FIXED_PROBABILITY_BINS; WILSON_95_INTERVAL; NO_THRESHOLD_AUTO_MUTATION'}
 return out

def run(ledger_path=LEDGER,out_path=OUT,snapshot_path=SNAPSHOT):
 ledger=json.loads(Path(ledger_path).read_text(encoding='utf-8'));out=build(ledger)
 Path(out_path).parent.mkdir(parents=True,exist_ok=True);Path(out_path).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 if Path(snapshot_path).exists():
  snap=json.loads(Path(snapshot_path).read_text(encoding='utf-8'));top=snap.setdefault('sports_top3',{});top['oos_probability_report']={'version':out['version'],'generated_at':out['generated_at'],'overall':out['overall'],'bins':out['bins'],'by_sport':out['by_sport'],'interpretation':out['interpretation'],'policy':out['policy']};Path(snapshot_path).write_text(json.dumps(snap,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'SPORTS_TOP3_PROBABILITY_REPORT':'PASS','observed':out['overall']['observed'],'evaluated':out['overall']['evaluated'],'state':out['interpretation']['state']},ensure_ascii=False))

def self_test():
 def r(eid,p,hit,sport='BASKETBALL'):
  return {'event_id':eid,'sport':sport,'top_p':p,'evaluation':None if hit is None else {'hit':hit}}
 ledger={'version':'TEST','records':{'a':r('a',.52,True),'b':r('b',.54,False),'c':r('c',.72,True),'d':r('d',.81,None),'e':r('e',.48,True,'SOCCER')}}
 out=build(ledger,datetime(2026,10,12,13,0,tzinfo=KST));assert out['overall']['observed']==5 and out['overall']['evaluated']==4 and out['overall']['hits']==3
 b=out['bins']['50_55'];assert b['evaluated']==2 and b['hits']==1 and b['hit_rate']==.5 and b['mean_model_p']==.53 and b['wilson95_lower'] is not None
 assert out['bins']['70_75']['hit_rate']==1.0 and out['bins']['75_PLUS']['pending']==1 and out['bins']['UNDER_50']['hits']==1
 assert out['interpretation']['state']=='HOLD_SAMPLE';print('SPORTS_TOP3_PROBABILITY_REPORT_SELF_TEST=PASS')

def main():
 a=argparse.ArgumentParser();a.add_argument('--self-test',action='store_true');x=a.parse_args();self_test() if x.self_test else run()
if __name__=='__main__':main()
