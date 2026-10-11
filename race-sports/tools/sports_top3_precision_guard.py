#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'data' / 'sports_today.json'
LOCK_FILE = ROOT / 'data' / 'model_state' / 'sports_top3_lock.json'
CIRCUIT_FILE = ROOT / 'data' / 'model_state' / 'sports_top3_circuit.json'
SPORTS = ('SOCCER','BASEBALL','BASKETBALL','VOLLEYBALL')
VERSION = 'SPORTS_TOP3_V4_PERFORMANCE_CIRCUIT'
MIN_TOP_P = {'SOCCER':0.58,'BASEBALL':0.62,'BASKETBALL':0.70,'VOLLEYBALL':0.70}
MIN_MARGIN = {'SOCCER':0.12,'BASEBALL':0.15,'BASKETBALL':0.20,'VOLLEYBALL':0.20}
MIN_COMP_GAMES=100
MIN_TEAM_GAMES=10


def _f(v,default=None):
    try:
        x=float(v);return x if math.isfinite(x) else default
    except Exception:return default


def _model_rows(event):
    rows=[]
    for o in event.get('outcomes',[]) or []:
        p=_f(o.get('model_p'));key=str(o.get('key') or '')
        if key and p is not None and p>0:rows.append((key,p))
    return sorted(rows,key=lambda x:x[1],reverse=True)


def _history_ok(event):
    h=event.get('model_history_scope') or {}
    return int(h.get('competition_games') or 0)>=MIN_COMP_GAMES and min(int(h.get('home_team_games') or 0),int(h.get('away_team_games') or 0))>=MIN_TEAM_GAMES


def qualify(entry,event):
    if not event:return False,'EVENT_NOT_IN_CURRENT_SNAPSHOT',None
    sport=str(event.get('sport') or entry.get('sport') or '')
    if sport not in SPORTS:return False,'UNSUPPORTED_SPORT',None
    if event.get('model_validated') is not True or event.get('model_state')!='VALIDATED_HOLDOUT':return False,'MODEL_NOT_VALIDATED',None
    if event.get('stale') or event.get('data_state')=='STALE_LAST_KNOWN_GOOD':return False,'STALE_DATA',None
    rows=_model_rows(event)
    if len(rows)<2:return False,'INCOMPLETE_MODEL_DISTRIBUTION',None
    top_key,top_p=rows[0];second_p=rows[1][1];margin=top_p-second_p
    m={'top_key':top_key,'top_p':top_p,'margin':margin}
    if str(entry.get('pick_key'))!=top_key:return False,'NOT_MODEL_TOP_PICK',m
    if top_p<MIN_TOP_P[sport]:return False,'TOP_PROBABILITY_BELOW_PRECISION_GATE',m
    if margin<MIN_MARGIN[sport]:return False,'MODEL_MARGIN_BELOW_PRECISION_GATE',m
    if not _history_ok(event):return False,'INSUFFICIENT_HISTORY',m
    return True,'PASS',m


def _safety(circuit,sport):
    if not isinstance(circuit,dict):return {'state':'NO_CIRCUIT','allow_new_picks':3}
    return dict((circuit.get('by_sport') or {}).get(sport) or {'state':'NO_CIRCUIT','allow_new_picks':3})


def _is_new_after_circuit(row,circuit):
    generated=str((circuit or {}).get('generated_at') or '')
    locked=str(row.get('locked_at') or '')
    return bool(generated and locked and locked>=generated)


def apply(snapshot,lock,circuit=None):
    board=snapshot.get('sports_top3')
    if not isinstance(board,dict):raise SystemExit('SPORTS_TOP3_MISSING')
    events={str(e.get('id')):e for e in snapshot.get('events',[]) if e.get('id')}
    lock=lock if isinstance(lock,dict) else None
    rejected=[];counts={};safety_public={}
    for sport in SPORTS:
        source=list((board.get('by_sport') or {}).get(sport) or [])
        kept=[];kept_ids=set();new_kept=0
        safety=_safety(circuit,sport);safety_public[sport]=safety
        state=str(safety.get('state') or 'NO_CIRCUIT')
        new_limit=int(safety.get('allow_new_picks',3) or 0)
        for row in source:
            eid=str(row.get('event_id') or '')
            ok,reason,metrics=qualify(row,events.get(eid))
            if not ok:
                rejected.append({'event_id':eid,'sport':sport,'reason':reason,'metrics':metrics});continue
            is_new=_is_new_after_circuit(row,circuit)
            if is_new and new_kept>=new_limit:
                rejected.append({'event_id':eid,'sport':sport,'reason':'PERFORMANCE_CIRCUIT_BREAKER','metrics':{'state':state,'allow_new_picks':new_limit}});continue
            x=dict(row);x['rank']=len(kept)+1;x['pick_basis']='MODEL_HIGH_CONFIDENCE';x['selection_type']='HIT_RATE';x['confidence']='HIGH_PRECISION'
            x['precision_gate']={'top_p':round(metrics['top_p'],8),'margin':round(metrics['margin'],8),'min_top_p':MIN_TOP_P[sport],'min_margin':MIN_MARGIN[sport]}
            x['performance_safety_state']=state
            kept.append(x);kept_ids.add(eid)
            if is_new:new_kept+=1
        board.setdefault('by_sport',{})[sport]=kept;counts[sport]=len(kept)
        if lock is not None:
            lb=lock.setdefault('by_sport',{});lb[sport]=[x for x in (lb.get(sport) or []) if str(x.get('event_id') or '') in kept_ids]
            for i,x in enumerate(lb[sport],1):x['rank']=i
    board['version']=VERSION
    board['selection_state']='HIGH_PRECISION_WITH_PERFORMANCE_CIRCUIT'
    board['policy']='MAX_3_PER_SPORT; MODEL_TOP_PICK_ONLY; VALIDATED_FRESH_ONLY; SPORT_SPECIFIC_PROBABILITY_AND_MARGIN_GATES; MIN_HISTORY; NO_FORCED_FILL; VALUE_AND_UPSET_EXCLUDED_FROM_HIT_RATE_BOARD; PERFORMANCE_CIRCUIT_BLOCKS_ONLY_NEW_PICKS; EXISTING_LOCKED_PICKS_RETAINED_THROUGH_RESULT'
    board['precision_thresholds']={'min_top_p':MIN_TOP_P,'min_margin':MIN_MARGIN,'min_competition_games':MIN_COMP_GAMES,'min_team_games_each':MIN_TEAM_GAMES}
    board['performance_safety']={'version':(circuit or {}).get('version'),'generated_at':(circuit or {}).get('generated_at'),'by_sport':safety_public}
    board['counts']=counts;board['rejected_count']=len(rejected);board['rejected_reason_counts']={}
    for r in rejected:board['rejected_reason_counts'][r['reason']]=board['rejected_reason_counts'].get(r['reason'],0)+1
    snapshot['sports_top3']=board
    return snapshot,lock,rejected


def run(snapshot_path=SNAPSHOT,lock_path=LOCK_FILE,circuit_path=CIRCUIT_FILE):
    snapshot=json.loads(Path(snapshot_path).read_text(encoding='utf-8'))
    lock=json.loads(Path(lock_path).read_text(encoding='utf-8')) if Path(lock_path).exists() else None
    circuit=json.loads(Path(circuit_path).read_text(encoding='utf-8')) if Path(circuit_path).exists() else None
    snapshot,lock,rejected=apply(snapshot,lock,circuit)
    Path(snapshot_path).write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
    if lock is not None:Path(lock_path).write_text(json.dumps(lock,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'SPORTS_TOP3_PRECISION_GUARD':'PASS','version':VERSION,'counts':snapshot['sports_top3']['counts'],'rejected':len(rejected),'reasons':snapshot['sports_top3']['rejected_reason_counts'],'safety':{s:v.get('state') for s,v in snapshot['sports_top3']['performance_safety']['by_sport'].items()}},ensure_ascii=False))


def self_test():
    def ev(eid,sport,p,q,comp=300,team=30):
        return {'id':eid,'sport':sport,'status':'SCHEDULED','data_state':'FRESH','model_validated':True,'model_state':'VALIDATED_HOLDOUT','model_history_scope':{'competition_games':comp,'home_team_games':team,'away_team_games':team},'outcomes':[{'key':'HOME','model_p':p},{'key':'AWAY','model_p':q}]}
    snap={'events':[ev('OLD','BASKETBALL',.76,.24),ev('NEW','BASKETBALL',.78,.22),ev('WEAK','BASKETBALL',.58,.42)],'sports_top3':{'by_sport':{'SOCCER':[],'BASEBALL':[],'BASKETBALL':[{'event_id':'OLD','sport':'BASKETBALL','pick_key':'HOME','locked_at':'2026-10-12T08:00:00+09:00'},{'event_id':'NEW','sport':'BASKETBALL','pick_key':'HOME','locked_at':'2026-10-12T09:01:00+09:00'},{'event_id':'WEAK','sport':'BASKETBALL','pick_key':'HOME','locked_at':'2026-10-12T09:02:00+09:00'}],'VOLLEYBALL':[]}}}
    lock={'by_sport':{s:list(snap['sports_top3']['by_sport'].get(s,[])) for s in SPORTS}}
    circuit={'version':'T','generated_at':'2026-10-12T09:00:00+09:00','by_sport':{'BASKETBALL':{'state':'BLOCK_24H','allow_new_picks':0}}}
    out,lock,rejected=apply(snap,lock,circuit)
    assert [x['event_id'] for x in out['sports_top3']['by_sport']['BASKETBALL']]==['OLD']
    assert any(r['reason']=='PERFORMANCE_CIRCUIT_BREAKER' for r in rejected)
    assert any(r['reason']=='TOP_PROBABILITY_BELOW_PRECISION_GATE' for r in rejected)
    print('SPORTS_TOP3_PRECISION_GUARD_SELF_TEST=PASS')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');a=ap.parse_args()
    self_test() if a.self_test else run()

if __name__=='__main__':main()
