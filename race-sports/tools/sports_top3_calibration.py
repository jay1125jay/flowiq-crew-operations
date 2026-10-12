#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];LEDGER=ROOT/'data'/'model_state'/'sports_top3_candidate_ledger.json';OUT=ROOT/'data'/'model_state'/'sports_top3_calibration.json'
KST=timezone(timedelta(hours=9));SPORTS=('SOCCER','BASEBALL','BASKETBALL','VOLLEYBALL');VERSION='SPORTS_TOP3_CALIBRATION_V2_UNBIASED_OOS_POOL'
BASE_P={'SOCCER':.58,'BASEBALL':.62,'BASKETBALL':.70,'VOLLEYBALL':.70};BASE_M={'SOCCER':.12,'BASEBALL':.15,'BASKETBALL':.20,'VOLLEYBALL':.20};MIN_EVAL=30;MIN_SELECTED=20;MIN_COVERAGE=.35

def _f(v):
 try:x=float(v);return x if math.isfinite(x) else None
 except Exception:return None
def _wilson(h,n,z=1.96):
 if n<=0:return None,None
 p=h/n;z2=z*z;d=1+z2/n;c=(p+z2/(2*n))/d;q=z*math.sqrt((p*(1-p)+z2/(4*n))/n)/d;return max(0,c-q),min(1,c+q)
def _rows(ledger,sport):
 out=[]
 for r in (ledger.get('records') or {}).values():
  if r.get('sport')!=sport:continue
  ev=r.get('evaluation') or {}
  if not isinstance(ev.get('hit'),bool):continue
  p=_f(r.get('top_p'));m=_f(r.get('margin'))
  if p is None or m is None:continue
  out.append({'p':p,'m':m,'hit':ev['hit'],'at':str(ev.get('evaluated_at') or r.get('observed_at') or '')})
 out.sort(key=lambda x:x['at']);return out
def _grid(base,values,step):
 vals={round(base,4)}
 for v in values:
  if v>=base:vals.add(round(math.floor(v/step)*step,4))
 return sorted(vals)
def calibrate_sport(rows,sport):
 n=len(rows);bp=BASE_P[sport];bm=BASE_M[sport]
 if n<MIN_EVAL:return {'state':'HOLD_SAMPLE','evaluated':n,'required':MIN_EVAL,'effective_min_top_p':bp,'effective_min_margin':bm,'source':'BASE_HEURISTIC_FLOOR'}
 cand=[]
 for p in _grid(bp,[x['p'] for x in rows],.02):
  for m in _grid(bm,[x['m'] for x in rows],.04):
   sel=[x for x in rows if x['p']>=p and x['m']>=m];sn=len(sel);cov=sn/n
   if sn<MIN_SELECTED or cov<MIN_COVERAGE:continue
   h=sum(1 for x in sel if x['hit']);lo,hi=_wilson(h,sn);cand.append({'min_top_p':p,'min_margin':m,'selected':sn,'coverage':cov,'hits':h,'hit_rate':h/sn,'wilson95_lower':lo,'wilson95_upper':hi})
 if not cand:return {'state':'HOLD_INSUFFICIENT_COVERAGE','evaluated':n,'required_selected':MIN_SELECTED,'min_coverage':MIN_COVERAGE,'effective_min_top_p':bp,'effective_min_margin':bm,'source':'BASE_HEURISTIC_FLOOR'}
 best=max(cand,key=lambda x:(x['wilson95_lower'],x['selected'],x['hit_rate']));base=next((x for x in cand if abs(x['min_top_p']-bp)<1e-9 and abs(x['min_margin']-bm)<1e-9),None);gain=(best['wilson95_lower']-(base or best)['wilson95_lower']) if base else 0.;active=(best['min_top_p']>bp or best['min_margin']>bm) and gain>=.02
 ep=best['min_top_p'] if active else bp;em=best['min_margin'] if active else bm
 fmt=lambda x:{k:(round(v,6) if isinstance(v,float) else v) for k,v in x.items()}
 return {'state':'CALIBRATED_TIGHTENED' if active else 'CALIBRATED_KEEP_BASE','evaluated':n,'effective_min_top_p':round(ep,4),'effective_min_margin':round(em,4),'source':'UNBIASED_PRE_EVENT_CANDIDATE_OOS','tighten_only':True,'min_selected':MIN_SELECTED,'min_coverage':MIN_COVERAGE,'best':fmt(best),'base':fmt(base) if base else None,'wilson_lower_gain':round(gain,6),'candidate_grid_size':len(cand)}
def build(ledger,now=None):
 now=now or datetime.now(KST);return {'version':VERSION,'generated_at':now.isoformat(timespec='seconds'),'by_sport':{s:calibrate_sport(_rows(ledger,s),s) for s in SPORTS},'policy':'TRUE_OOS_SOURCE=ALL_ELIGIBLE_PRE_EVENT_CANDIDATES_BEFORE_PRECISION_THRESHOLD; IMMUTABLE_FIRST_OBSERVATION; MIN_30_EVALUATED; MIN_20_SELECTED; MIN_35PCT_COVERAGE; OPTIMIZE_WILSON95_LOWER; REQUIRE_2PCT_LOWER_BOUND_GAIN_TO_TIGHTEN; NEVER_RELAX_BELOW_BASE; NO_TOP3_SELECTION_BIAS; NO_FUTURE_RESULT_LEAKAGE'}
def run(ledger_path=LEDGER,out_path=OUT):
 ledger=json.loads(Path(ledger_path).read_text(encoding='utf-8')) if Path(ledger_path).exists() else {};out=build(ledger);Path(out_path).parent.mkdir(parents=True,exist_ok=True);Path(out_path).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'SPORTS_TOP3_CALIBRATION':'PASS','version':VERSION,'states':{s:v['state'] for s,v in out['by_sport'].items()}},ensure_ascii=False))
def self_test():
 ledger={'records':{}}
 for i in range(40):
  high=i>=20;p=.82 if high else .71;m=.42 if high else .22;hit=(i%10!=0) if high else (i%2==0)
  ledger['records'][str(i)]={'sport':'BASKETBALL','top_p':p,'margin':m,'observed_at':f'2026-10-{1+i//4:02d}T09:00:00+09:00','evaluation':{'hit':hit,'evaluated_at':f'2026-10-{1+i//4:02d}T12:00:00+09:00'}}
 out=build(ledger,datetime(2026,10,12,12,0,tzinfo=KST));b=out['by_sport']['BASKETBALL'];assert b['state']=='CALIBRATED_TIGHTENED',b;assert b['effective_min_top_p']>=BASE_P['BASKETBALL'] and b['effective_min_margin']>=BASE_M['BASKETBALL'];assert out['by_sport']['SOCCER']['state']=='HOLD_SAMPLE';print('SPORTS_TOP3_CALIBRATION_SELF_TEST=PASS')
def main():
 a=argparse.ArgumentParser();a.add_argument('--self-test',action='store_true');x=a.parse_args();self_test() if x.self_test else run()
if __name__=='__main__':main()
