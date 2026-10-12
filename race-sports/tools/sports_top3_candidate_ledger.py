#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SNAPSHOT=ROOT/'data'/'sports_today.json';HISTORY_DIR=ROOT/'data'/'sports_history';OUT=ROOT/'data'/'model_state'/'sports_top3_candidate_ledger.json'
KST=timezone(timedelta(hours=9));SPORTS=('SOCCER','BASEBALL','BASKETBALL','VOLLEYBALL');VERSION='SPORTS_TOP3_CANDIDATE_LEDGER_V1_TRUE_OOS';MIN_COMP_GAMES=100;MIN_TEAM_GAMES=10

def _f(v):
 try:x=float(v);return x if math.isfinite(x) else None
 except Exception:return None

def _fresh(e):return not e.get('stale') and e.get('data_state')!='STALE_LAST_KNOWN_GOOD'
def _model_rows(e):
 r=[]
 for o in e.get('outcomes',[]) or []:
  p=_f(o.get('model_p'));k=str(o.get('key') or '')
  if k and p is not None and p>0:r.append((k,p))
 return sorted(r,key=lambda x:x[1],reverse=True)
def _scope(e):
 h=e.get('model_history_scope') or {};return {'competition_games':int(h.get('competition_games') or 0),'home_team_games':int(h.get('home_team_games') or 0),'away_team_games':int(h.get('away_team_games') or 0)}
def _eligible(e):
 if str(e.get('sport') or '') not in SPORTS or e.get('status')!='SCHEDULED' or not _fresh(e):return False
 if e.get('model_validated') is not True or e.get('model_state')!='VALIDATED_HOLDOUT':return False
 if len(_model_rows(e))<2:return False
 h=_scope(e);return h['competition_games']>=MIN_COMP_GAMES and min(h['home_team_games'],h['away_team_games'])>=MIN_TEAM_GAMES
def _winner(e):
 r=e.get('result') or {};wk=r.get('winner_key')
 if wk in {'HOME','AWAY','DRAW'}:return wk
 try:hs,aw=float(r['home_score']),float(r['away_score'])
 except Exception:return None
 if hs>aw:return 'HOME'
 if aw>hs:return 'AWAY'
 return 'DRAW' if e.get('sport')=='SOCCER' else None
def _result_index(snapshot,history_dir=HISTORY_DIR):
 idx={};docs=[]
 if Path(history_dir).exists():
  for p in sorted(Path(history_dir).glob('*.json')):
   try:docs.append(json.loads(p.read_text(encoding='utf-8')))
   except Exception:pass
 docs.append(snapshot)
 for doc in docs:
  for e in doc.get('events',[]) or []:
   eid=str(e.get('id') or '')
   if not eid or e.get('status')!='FINAL':continue
   wk=_winner(e)
   if wk:idx[eid]={'winner_key':wk,'source_snapshot_date':doc.get('date')}
 return idx

def build(snapshot,ledger=None,now=None,result_index=None):
 now=now or datetime.now(KST);now_iso=now.isoformat(timespec='seconds')
 if not isinstance(ledger,dict) or ledger.get('version')!=VERSION:ledger={'version':VERSION,'created_at':now_iso,'records':{}}
 records=ledger.setdefault('records',{});added=0
 # First eligible PRE-EVENT observation is immutable. This prevents future-result leakage.
 for e in snapshot.get('events',[]) or []:
  eid=str(e.get('id') or '')
  if not eid or eid in records or not _eligible(e):continue
  rows=_model_rows(e);top_key,top_p=rows[0];second_key,second_p=rows[1];h=_scope(e)
  records[eid]={'event_id':eid,'sport':e.get('sport'),'competition':e.get('competition'),'event_date':e.get('event_date'),'start_time':e.get('start_time'),'start_timestamp':e.get('start_timestamp'),'title':e.get('title') or f"{e.get('home')} vs {e.get('away')}",'home':e.get('home'),'away':e.get('away'),'top_key':top_key,'top_p':round(top_p,10),'second_key':second_key,'second_p':round(second_p,10),'margin':round(top_p-second_p,10),'model_source':e.get('model_source'),'model_state':e.get('model_state'),'history':h,'observed_at':now_iso,'observation_state':'PRE_EVENT_SCHEDULED','evaluation':None};added+=1
 result_index=result_index or {};resolved=0
 for eid,r in records.items():
  if isinstance((r.get('evaluation') or {}).get('hit'),bool):continue
  final=result_index.get(eid)
  if not final:continue
  wk=final['winner_key'];r['evaluation']={'winner_key':wk,'hit':wk==r.get('top_key'),'evaluated_at':now_iso,'source_snapshot_date':final.get('source_snapshot_date')};resolved+=1
 by={}
 for sport in SPORTS:
  rs=[r for r in records.values() if r.get('sport')==sport];ev=[r for r in rs if isinstance((r.get('evaluation') or {}).get('hit'),bool)];hits=sum(1 for r in ev if r['evaluation']['hit'])
  by[sport]={'observed':len(rs),'evaluated':len(ev),'pending':len(rs)-len(ev),'hits':hits,'misses':len(ev)-hits,'hit_rate':round(hits/len(ev),6) if ev else None}
 allr=list(records.values());alle=[r for r in allr if isinstance((r.get('evaluation') or {}).get('hit'),bool)];hits=sum(1 for r in alle if r['evaluation']['hit'])
 ledger['updated_at']=now_iso;ledger['summary']={'observed':len(allr),'evaluated':len(alle),'pending':len(allr)-len(alle),'hits':hits,'misses':len(alle)-hits,'hit_rate':round(hits/len(alle),6) if alle else None,'by_sport':by}
 ledger['eligibility_contract']={'status':'SCHEDULED','fresh_only':True,'model_validated':True,'model_state':'VALIDATED_HOLDOUT','min_competition_games':MIN_COMP_GAMES,'min_team_games_each':MIN_TEAM_GAMES,'threshold_gate_applied':False,'market_gate_applied':False}
 ledger['policy']='APPEND_ONLY_FIRST_PRE_EVENT_OBSERVATION; ALL_PRECISION_ELIGIBLE_CANDIDATES_BEFORE_P_OR_MARGIN_GATE; IMMUTABLE_PREDICTION; FINAL_RESULT_ONLY_EVALUATION; HISTORY_LOOKUP_ONLY_FOR_POST_EVENT_RESULT; NO_SELECTION_BIAS_FROM_TOP3_LOCK; NO_FUTURE_RESULT_LEAKAGE'
 return ledger,added,resolved

def run(snapshot_path=SNAPSHOT,out_path=OUT,history_dir=HISTORY_DIR):
 snapshot=json.loads(Path(snapshot_path).read_text(encoding='utf-8'));ledger=None
 if Path(out_path).exists():
  try:ledger=json.loads(Path(out_path).read_text(encoding='utf-8'))
  except Exception:ledger=None
 out,added,resolved=build(snapshot,ledger,result_index=_result_index(snapshot,Path(history_dir)));Path(out_path).parent.mkdir(parents=True,exist_ok=True);Path(out_path).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'SPORTS_TOP3_CANDIDATE_LEDGER':'PASS','added':added,'resolved':resolved,'summary':out['summary']},ensure_ascii=False))
def self_test():
 def ev(eid,status='SCHEDULED',p=.78,q=.22):
  x={'id':eid,'sport':'BASKETBALL','status':status,'data_state':'FRESH','competition':'NBA','event_date':'2026-10-12','model_validated':True,'model_state':'VALIDATED_HOLDOUT','model_source':'test','model_history_scope':{'competition_games':300,'home_team_games':30,'away_team_games':30},'outcomes':[{'key':'HOME','model_p':p},{'key':'AWAY','model_p':q}]}
  if status=='FINAL':x['result']={'winner_key':'HOME','home_score':100,'away_score':90}
  return x
 now=datetime(2026,10,12,9,0,tzinfo=KST);snap={'date':'2026-10-12','events':[ev('E1'),ev('WEAKHIST')]};snap['events'][1]['model_history_scope']['competition_games']=20
 ledger,a,r=build(snap,None,now,{});assert a==1 and r==0 and 'E1' in ledger['records'] and 'WEAKHIST' not in ledger['records'];first=ledger['records']['E1']['top_p']
 later={'date':'2026-10-12','events':[ev('E1','FINAL',.55,.45)]};idx={'E1':{'winner_key':'HOME','source_snapshot_date':'2026-10-12'}};ledger,a2,r2=build(later,ledger,now+timedelta(hours=4),idx)
 assert a2==0 and r2==1 and ledger['records']['E1']['top_p']==first and ledger['records']['E1']['evaluation']['hit'] is True
 print('SPORTS_TOP3_CANDIDATE_LEDGER_SELF_TEST=PASS')
def main():
 a=argparse.ArgumentParser();a.add_argument('--self-test',action='store_true');x=a.parse_args();self_test() if x.self_test else run()
if __name__=='__main__':main()
