#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SNAPSHOT=ROOT/'data'/'sports_today.json';LOCK_FILE=ROOT/'data'/'model_state'/'sports_top3_lock.json';CIRCUIT_FILE=ROOT/'data'/'model_state'/'sports_top3_circuit.json';CALIB_FILE=ROOT/'data'/'model_state'/'sports_top3_calibration.json'
SPORTS=('SOCCER','BASEBALL','BASKETBALL','VOLLEYBALL');VERSION='SPORTS_TOP3_V5_OOS_CALIBRATED'
BASE_P={'SOCCER':.58,'BASEBALL':.62,'BASKETBALL':.70,'VOLLEYBALL':.70};BASE_M={'SOCCER':.12,'BASEBALL':.15,'BASKETBALL':.20,'VOLLEYBALL':.20};MIN_COMP_GAMES=100;MIN_TEAM_GAMES=10

def _f(v,d=None):
 try:x=float(v);return x if math.isfinite(x) else d
 except:return d

def _model_rows(e):
 r=[]
 for o in e.get('outcomes',[]) or []:
  p=_f(o.get('model_p'));k=str(o.get('key') or '')
  if k and p is not None and p>0:r.append((k,p))
 return sorted(r,key=lambda x:x[1],reverse=True)
def _history_ok(e):
 h=e.get('model_history_scope') or {};return int(h.get('competition_games') or 0)>=MIN_COMP_GAMES and min(int(h.get('home_team_games') or 0),int(h.get('away_team_games') or 0))>=MIN_TEAM_GAMES
def _thresholds(calib,sport,row):
 p,m=BASE_P[sport],BASE_M[sport];src='BASE_HEURISTIC_FLOOR';state='NO_CALIBRATION'
 c=((calib or {}).get('by_sport') or {}).get(sport) or {};state=str(c.get('state') or state)
 generated=str((calib or {}).get('generated_at') or '');locked=str(row.get('locked_at') or '')
 # A pick locked before this calibration snapshot is grandfathered. New picks use calibrated gates.
 if generated and locked and locked>=generated and state in {'CALIBRATED_TIGHTENED','CALIBRATED_KEEP_BASE'}:
  p=max(p,_f(c.get('effective_min_top_p'),p));m=max(m,_f(c.get('effective_min_margin'),m));src='LIVE_LOCKED_OOS_CALIBRATION'
 return p,m,src,state
def qualify(entry,event,min_p,min_m):
 if not event:return False,'EVENT_NOT_IN_CURRENT_SNAPSHOT',None
 sport=str(event.get('sport') or entry.get('sport') or '')
 if sport not in SPORTS:return False,'UNSUPPORTED_SPORT',None
 if event.get('model_validated') is not True or event.get('model_state')!='VALIDATED_HOLDOUT':return False,'MODEL_NOT_VALIDATED',None
 if event.get('stale') or event.get('data_state')=='STALE_LAST_KNOWN_GOOD':return False,'STALE_DATA',None
 rows=_model_rows(event)
 if len(rows)<2:return False,'INCOMPLETE_MODEL_DISTRIBUTION',None
 top_key,top_p=rows[0];margin=top_p-rows[1][1];met={'top_key':top_key,'top_p':top_p,'margin':margin}
 if str(entry.get('pick_key'))!=top_key:return False,'NOT_MODEL_TOP_PICK',met
 if top_p<min_p:return False,'TOP_PROBABILITY_BELOW_PRECISION_GATE',met
 if margin<min_m:return False,'MODEL_MARGIN_BELOW_PRECISION_GATE',met
 if not _history_ok(event):return False,'INSUFFICIENT_HISTORY',met
 return True,'PASS',met
def _safety(c,s):return dict(((c or {}).get('by_sport') or {}).get(s) or {'state':'NO_CIRCUIT','allow_new_picks':3})
def _is_new(row,obj):
 g=str((obj or {}).get('generated_at') or '');l=str(row.get('locked_at') or '');return bool(g and l and l>=g)
def apply(snapshot,lock,circuit=None,calib=None):
 board=snapshot.get('sports_top3');
 if not isinstance(board,dict):raise SystemExit('SPORTS_TOP3_MISSING')
 events={str(e.get('id')):e for e in snapshot.get('events',[]) if e.get('id')};lock=lock if isinstance(lock,dict) else None;rejected=[];counts={};spub={};cpub={}
 for sport in SPORTS:
  source=list((board.get('by_sport') or {}).get(sport) or []);kept=[];ids=set();new_kept=0;safety=_safety(circuit,sport);spub[sport]=safety;limit=int(safety.get('allow_new_picks',3) or 0)
  for row in source:
   eid=str(row.get('event_id') or '');minp,minm,tsrc,cstate=_thresholds(calib,sport,row);cpub[sport]={'state':cstate,'effective_min_top_p':minp,'effective_min_margin':minm,'source':tsrc}
   ok,reason,met=qualify(row,events.get(eid),minp,minm)
   if not ok:rejected.append({'event_id':eid,'sport':sport,'reason':reason,'metrics':met});continue
   isnew=_is_new(row,circuit)
   if isnew and new_kept>=limit:rejected.append({'event_id':eid,'sport':sport,'reason':'PERFORMANCE_CIRCUIT_BREAKER','metrics':{'state':safety.get('state'),'allow_new_picks':limit}});continue
   x=dict(row);x['rank']=len(kept)+1;x['pick_basis']='MODEL_HIGH_CONFIDENCE';x['selection_type']='HIT_RATE';x['confidence']='HIGH_PRECISION';x['precision_gate']={'top_p':round(met['top_p'],8),'margin':round(met['margin'],8),'min_top_p':minp,'min_margin':minm,'threshold_source':tsrc};x['performance_safety_state']=str(safety.get('state') or 'NO_CIRCUIT');kept.append(x);ids.add(eid);new_kept+=1 if isnew else 0
  board.setdefault('by_sport',{})[sport]=kept;counts[sport]=len(kept)
  if sport not in cpub:cpub[sport]={'state':str((((calib or {}).get('by_sport') or {}).get(sport) or {}).get('state') or 'NO_CALIBRATION'),'effective_min_top_p':BASE_P[sport],'effective_min_margin':BASE_M[sport],'source':'BASE_HEURISTIC_FLOOR'}
  if lock is not None:
   lb=lock.setdefault('by_sport',{});lb[sport]=[x for x in (lb.get(sport) or []) if str(x.get('event_id') or '') in ids]
   for i,x in enumerate(lb[sport],1):x['rank']=i
 board['version']=VERSION;board['selection_state']='HIGH_PRECISION_WITH_PERFORMANCE_CIRCUIT_AND_OOS_CALIBRATION';board['policy']='MODEL_TOP_PICK_ONLY; VALIDATED_FRESH_ONLY; BASE_GATES_ARE_FLOORS; OOS_CALIBRATION_CAN_TIGHTEN_NEW_PICKS_ONLY; EXISTING_LOCKED_PICKS_GRANDFATHERED; CIRCUIT_BREAKER; NO_FORCED_FILL'
 board['precision_thresholds']={'base_min_top_p':BASE_P,'base_min_margin':BASE_M,'min_competition_games':MIN_COMP_GAMES,'min_team_games_each':MIN_TEAM_GAMES,'calibration':cpub};board['performance_safety']={'version':(circuit or {}).get('version'),'generated_at':(circuit or {}).get('generated_at'),'by_sport':spub};board['calibration']={'version':(calib or {}).get('version'),'generated_at':(calib or {}).get('generated_at'),'by_sport':cpub};board['counts']=counts;board['rejected_count']=len(rejected);board['rejected_reason_counts']={}
 for r in rejected:board['rejected_reason_counts'][r['reason']]=board['rejected_reason_counts'].get(r['reason'],0)+1
 return snapshot,lock,rejected
def run(snapshot_path=SNAPSHOT,lock_path=LOCK_FILE,circuit_path=CIRCUIT_FILE,calib_path=CALIB_FILE):
 snapshot=json.loads(Path(snapshot_path).read_text(encoding='utf-8'));lock=json.loads(Path(lock_path).read_text(encoding='utf-8')) if Path(lock_path).exists() else None;circuit=json.loads(Path(circuit_path).read_text(encoding='utf-8')) if Path(circuit_path).exists() else None;calib=json.loads(Path(calib_path).read_text(encoding='utf-8')) if Path(calib_path).exists() else None;snapshot,lock,rej=apply(snapshot,lock,circuit,calib);Path(snapshot_path).write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8');
 if lock is not None:Path(lock_path).write_text(json.dumps(lock,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'SPORTS_TOP3_PRECISION_GUARD':'PASS','version':VERSION,'counts':snapshot['sports_top3']['counts'],'rejected':len(rej)},ensure_ascii=False))
def self_test():
 def ev(i,p,q):return {'id':i,'sport':'BASKETBALL','data_state':'FRESH','model_validated':True,'model_state':'VALIDATED_HOLDOUT','model_history_scope':{'competition_games':300,'home_team_games':30,'away_team_games':30},'outcomes':[{'key':'HOME','model_p':p},{'key':'AWAY','model_p':q}]}
 rows=[{'event_id':'OLD','sport':'BASKETBALL','pick_key':'HOME','locked_at':'2026-10-12T08:00:00+09:00'},{'event_id':'NEW','sport':'BASKETBALL','pick_key':'HOME','locked_at':'2026-10-12T10:01:00+09:00'}];snap={'events':[ev('OLD',.75,.25),ev('NEW',.75,.25)],'sports_top3':{'by_sport':{s:(rows if s=='BASKETBALL' else []) for s in SPORTS}}};lock={'by_sport':{s:list(snap['sports_top3']['by_sport'][s]) for s in SPORTS}};c={'generated_at':'2026-10-12T07:00:00+09:00','by_sport':{'BASKETBALL':{'state':'ACTIVE','allow_new_picks':3}}};cal={'version':'T','generated_at':'2026-10-12T10:00:00+09:00','by_sport':{'BASKETBALL':{'state':'CALIBRATED_TIGHTENED','effective_min_top_p':.80,'effective_min_margin':.30}}};out,_,rej=apply(snap,lock,c,cal);assert [x['event_id'] for x in out['sports_top3']['by_sport']['BASKETBALL']]==['OLD'];assert any(r['event_id']=='NEW' and r['reason']=='TOP_PROBABILITY_BELOW_PRECISION_GATE' for r in rej);print('SPORTS_TOP3_PRECISION_GUARD_SELF_TEST=PASS')
def main():
 a=argparse.ArgumentParser();a.add_argument('--self-test',action='store_true');x=a.parse_args();self_test() if x.self_test else run()
if __name__=='__main__':main()
