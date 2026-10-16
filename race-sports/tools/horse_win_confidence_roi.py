#!/usr/bin/env python3
"""Fixed-cohort, discovery-only threshold selection; final odds settle only."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import validate_horse_model as hv

OUT=Path('race-sports/models/horse_win_confidence_roi.json')
LOCK=Path('race-sports/data/model_state/horse_win_confidence_experiment.json')
KST=timezone(timedelta(hours=9))
STAKE=100000
VERSION='HORSE_WIN_CONFIDENCE_ROI_V2_FROZEN_DATE_BATCH'
MIN_DISCOVERY_BETS=150
MIN_HOLDOUT_BETS=75
DISCOVERY_FRAC=.60

def fingerprint(races):
    # Hash only the actual model/settlement inputs, not fetch timestamps.
    fields=hv.FEATURES+['number','final_rank','won','final_odds']
    obj=[{'id':e.get('id'),'date':e.get('event_date'),'result':{k:(e.get('result') or {}).get(k) for k in ['status','winner_number','top3']},
          'outcomes':[{k:o.get(k) for k in fields} for o in e.get('outcomes',[])]} for e in races]
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def build_rows(races=None):
    races=hv.records() if races is None else races
    rows=[];warmup=0
    for e,probs,is_oos in hv.walk_forward_predictions(races):
        if not is_oos: warmup+=1;continue
        order=sorted(range(len(probs)),key=lambda j:probs[j],reverse=True)
        if len(order)<2:continue
        pred=order[0];outs=e['outcomes']
        odds=hv.sf(outs[pred].get('final_odds'))
        rows.append({'event_id':e.get('id'),'event_date':e.get('event_date'),
                     'top_p':probs[pred],'margin':probs[pred]-probs[order[1]],
                     'odds':odds if odds is not None and odds>0 else None,
                     'hit':hv.win_label(e,outs[pred])==1})
    return races,warmup,rows

def split_rows(rows):
    cut=int(len(rows)*DISCOVERY_FRAC)
    # Never split one date between discovery and holdout.
    while 0<cut<len(rows) and rows[cut-1]['event_date']==rows[cut]['event_date']:cut+=1
    return rows[:cut],rows[cut:]

def metric(rows,pmin,mmin=0):
    selected=[r for r in rows if r['top_p']>=pmin and r['margin']>=mmin]
    settled=[r for r in selected if hv.sf(r['odds']) is not None and r['odds']>0]
    n=len(selected);hits=sum(r['hit'] for r in selected)
    stake=len(settled)*STAKE;returned=sum(STAKE*r['odds'] for r in settled if r['hit'])
    return {'bets':n,'hits':hits,'hit_rate':round(hits/n,8) if n else None,
            'roi_bets':len(settled),'excluded_missing_odds':n-len(settled),
            'total_staked_krw':stake,'total_return_krw':round(returned),
            'net_profit_krw':round(returned-stake),'roi':round(returned/stake-1,8) if stake else None,
            'coverage':round(n/len(rows),8) if rows else None}

def p_grid(_=None):return [x/1000 for x in range(80,501,5)]
def m_grid():return [x/1000 for x in range(0,201,10)]

def choose(discovery):
    all_candidates=[]
    for p in p_grid():
        for m in m_grid():
            d=metric(discovery,p,m)
            all_candidates.append({'top_p_min':p,'margin_min':m,'discovery':d})
    valid=[r for r in all_candidates if r['discovery']['roi_bets']>=MIN_DISCOVERY_BETS]
    rules=[]
    for family,pool in [('PROBABILITY_ONLY',[r for r in valid if r['margin_min']==0]),('PROBABILITY_PLUS_MARGIN',valid)]:
        positive=[r for r in pool if r['discovery']['roi']>=0]
        if positive:
            broad=max(positive,key=lambda r:(r['discovery']['bets'],r['discovery']['roi'],-r['top_p_min'],-r['margin_min']))
            rules.append({'name':'BROADEST_NONNEGATIVE_'+family,**broad})
        if pool:
            best=max(pool,key=lambda r:(r['discovery']['roi'],r['discovery']['bets'],-r['top_p_min'],-r['margin_min']))
            rules.append({'name':'BEST_DISCOVERY_'+family,**best})
    # Primary rule selected before reading holdout. Never choose by holdout ROI.
    primary=max(rules,key=lambda r:(r['discovery']['roi'],r['discovery']['bets']))['name'] if rules else None
    return rules,primary,all_candidates

def state(d,h):
    if d['roi_bets']<MIN_DISCOVERY_BETS or h['roi_bets']<MIN_HOLDOUT_BETS:return 'HOLD_SMALL_SAMPLE'
    if d['roi']<0 or h['roi']<0:return 'FAIL'
    # These historical dates were already examined in V1: cannot claim untouched.
    return 'HOLD_REUSED_HISTORICAL_HOLDOUT'

def main():
    current=hv.records();lock=json.loads(LOCK.read_text()) if LOCK.exists() else None
    if lock:
        ids=set(lock['input_event_ids']);races=[e for e in current if e.get('id') in ids]
        if len(races)!=len(ids) or fingerprint(races)!=lock['input_sha256']:
            raise SystemExit('FROZEN_COHORT_CHANGED: do not retune; inspect corrected source records')
    else:races=current
    races,warmup,rows=build_rows(races);discovery,holdout=split_rows(rows)
    if lock:
        rules=lock['rules'];primary=lock['primary_rule'];candidates=None
        if [r['event_id'] for r in discovery]!=lock['discovery_event_ids']:raise SystemExit('FROZEN_SPLIT_CHANGED')
    else:
        rules,primary,candidates=choose(discovery)
        lock={'version':VERSION,'created_at':datetime.now(KST).isoformat(timespec='seconds'),
              'input_event_ids':[e['id'] for e in races],'input_sha256':fingerprint(races),
              'discovery_event_ids':[r['event_id'] for r in discovery],
              'rules':rules,'primary_rule':primary,'holdout_previously_examined':True,
              'policy':'IMMUTABLE_COHORT_AND_RULES; NEW_BACKFILL_DOES_NOT_RETUNE; V1_HOLDOUT_REUSED_RESEARCH_ONLY'}
        LOCK.parent.mkdir(parents=True,exist_ok=True);LOCK.write_text(json.dumps(lock,ensure_ascii=False,indent=2))
    # Recreate discovery table for audit only; never change frozen selected rules.
    if candidates is None:candidates=choose(discovery)[2]
    evaluated=[]
    for rule in rules:
        h=metric(holdout,rule['top_p_min'],rule['margin_min'])
        evaluated.append({**rule,'holdout':h,'state':state(rule['discovery'],h)})
    # Display the fixed grid without using holdout metrics for rule selection.
    for candidate in candidates:
        candidate['holdout']=metric(holdout,candidate['top_p_min'],candidate['margin_min'])
    primary_result=next((r for r in evaluated if r['name']==primary),None)
    conclusion='NO_OOS_PROFITABLE_THRESHOLD_FOUND'
    if primary_result and primary_result['state']=='HOLD_REUSED_HISTORICAL_HOLDOUT':conclusion='HOLD_REQUIRES_NEW_UNTOUCHED_FORWARD_SAMPLE'
    if not primary_result or primary_result['state']=='HOLD_SMALL_SAMPLE':conclusion='HOLD_SMALL_SAMPLE'
    report={'version':VERSION,'generated_at':datetime.now(KST).isoformat(timespec='seconds'),
            'model_source':hv.MODEL_SOURCE,'input_races':len(races),'current_available_races':len(current),
            'warmup_races':warmup,'walk_forward_races':len(rows),
            'odds_eligible_walk_forward_races':sum(r['odds'] is not None for r in rows),
            'split':{'method':'FROZEN_CHRONOLOGICAL_60_40_WHOLE_DATES','discovery_races':len(discovery),
                     'holdout_races':len(holdout),'discovery_end':discovery[-1]['event_date'] if discovery else None,
                     'holdout_start':holdout[0]['event_date'] if holdout else None,'holdout_is_new_untouched':False},
            'stake_per_selected_race_krw':STAKE,'min_discovery_bets':MIN_DISCOVERY_BETS,'min_holdout_bets':MIN_HOLDOUT_BETS,
            'primary_rule':primary,'rules':evaluated,'candidate_count':len(candidates),
            'discovery_candidates':candidates,'conclusion':conclusion,
            'value_filter':{'state':'BLOCKED_NO_HISTORICAL_PRE_RACE_ODDS','reason':'Final tote odds cannot be used as a pre-race EV selection feature'},
            'policy':'PREDICT_ENTIRE_DATE_THEN_UPDATE; FIXED_GRID; DISCOVERY_ONLY_SELECTION; FROZEN_COHORT_AND_RULES; MISSING_ODDS_EXCLUDED_FROM_ROI_NOT_PREDICTION_OR_SPLIT',
            'warning':'V1 already exposed these historical holdout dates. This correction is retrospective revalidation, not a new untouched test. No live betting.'}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='discovery_candidates'},ensure_ascii=False))
if __name__=='__main__':main()
