#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import validate_horse_model as hv

OUT = Path('race-sports/models/horse_win_confidence_roi.json')
KST = timezone(timedelta(hours=9))
STAKE = 100000
VERSION = 'HORSE_WIN_CONFIDENCE_ROI_V1_CHRONOLOGICAL_OOS'
MIN_DISCOVERY_BETS = 150
MIN_HOLDOUT_BETS = 75
DISCOVERY_FRAC = 0.60


def rank_index(event, rank):
    for i, o in enumerate(event.get('outcomes') or []):
        try:
            if int(o.get('final_rank')) == rank:
                return i
        except Exception:
            pass
    return None


def build_rows():
    races = hv.records()
    stats = {'horse': defaultdict(lambda:[0,0]), 'jockey': defaultdict(lambda:[0,0]), 'trainer': defaultdict(lambda:[0,0])}
    total_starts = total_wins = 0
    warmup = max(100, int(len(races) * .30)) if races else 0
    rows = []
    for i, e in enumerate(races):
        outs = e.get('outcomes') or []
        base = (total_wins / total_starts) if total_starts else .10
        if i >= warmup and len(outs) >= 2:
            probs = hv.score(e, stats, base)
            first = rank_index(e, 1)
            if probs and first is not None:
                order = sorted(range(len(probs)), key=lambda j: probs[j], reverse=True)
                pred = order[0]
                try: odds = float(outs[pred].get('final_odds'))
                except Exception: odds = 0.0
                if odds > 0:
                    p1 = float(probs[pred])
                    p2 = float(probs[order[1]]) if len(order) > 1 else 0.0
                    rows.append({
                        'event_id': e.get('id'), 'event_date': e.get('event_date'),
                        'top_p': p1, 'margin': p1-p2, 'odds': odds, 'hit': pred == first,
                    })
        s,w = hv.update(stats,e); total_starts += s; total_wins += w
    return races, warmup, rows


def metric(rows, pmin, mmin=0.0):
    selected = [r for r in rows if r['top_p'] >= pmin and r['margin'] >= mmin]
    n = len(selected); hits = sum(int(r['hit']) for r in selected)
    staked = n * STAKE
    returned = sum(STAKE * r['odds'] for r in selected if r['hit'])
    net = returned - staked
    return {
        'bets': n, 'hits': hits, 'hit_rate': round(hits/n,8) if n else None,
        'total_staked_krw': int(staked), 'total_return_krw': round(returned),
        'net_profit_krw': round(net), 'roi': round(net/staked,8) if staked else None,
        'coverage': round(n/len(rows),8) if rows else None,
    }


def p_grid(rows):
    # Dense, deterministic probability grid; thresholds are pre-race model probabilities only.
    vals = {round(x/1000,3) for x in range(80, 501, 5)}
    vals |= {round(r['top_p'],3) for r in rows}
    return sorted(x for x in vals if .05 <= x <= .70)


def m_grid():
    return [round(x/1000,3) for x in range(0, 201, 10)]


def find_probability_threshold(discovery):
    candidates=[]
    for p in p_grid(discovery):
        m=metric(discovery,p,0.0)
        if m['bets'] >= MIN_DISCOVERY_BETS:
            candidates.append((p,m))
    profitable=[x for x in candidates if x[1]['roi'] is not None and x[1]['roi'] >= 0]
    breakeven=min(profitable,key=lambda x:x[0]) if profitable else None
    best=max(candidates,key=lambda x:(x[1]['roi'],x[1]['bets'])) if candidates else None
    return breakeven,best


def find_probability_margin(discovery):
    candidates=[]
    for p in p_grid(discovery):
        for margin in m_grid():
            m=metric(discovery,p,margin)
            if m['bets'] >= MIN_DISCOVERY_BETS:
                candidates.append((p,margin,m))
    profitable=[x for x in candidates if x[2]['roi'] is not None and x[2]['roi'] >= 0]
    # Prefer broadest profitable rule first, then ROI. This avoids selecting a tiny lucky slice.
    breakeven=max(profitable,key=lambda x:(x[2]['bets'],x[2]['roi'])) if profitable else None
    best=max(candidates,key=lambda x:(x[2]['roi'],x[2]['bets'])) if candidates else None
    return breakeven,best


def pack_rule(name, rule, holdout, with_margin=False):
    if not rule:
        return {'name':name,'state':'NO_DISCOVERY_RULE'}
    if with_margin:
        p,margin,disc=rule
    else:
        p,disc=rule; margin=0.0
    test=metric(holdout,p,margin)
    state='OOS_PASS_POSITIVE_ROI' if test['bets'] >= MIN_HOLDOUT_BETS and test['roi'] is not None and test['roi'] >= 0 else 'OOS_FAIL_NOT_PROFITABLE'
    if test['bets'] < MIN_HOLDOUT_BETS: state='OOS_HOLD_SMALL_SAMPLE'
    return {'name':name,'state':state,'top_p_min':p,'margin_min':margin,'discovery':disc,'holdout':test}


def main():
    races,warmup,rows=build_rows()
    cut=max(1,min(len(rows)-1,int(len(rows)*DISCOVERY_FRAC))) if len(rows)>1 else len(rows)
    discovery,holdout=rows[:cut],rows[cut:]
    p_break,p_best=find_probability_threshold(discovery)
    pm_break,pm_best=find_probability_margin(discovery)
    rules=[
        pack_rule('LOWEST_PROBABILITY_THRESHOLD_WITH_NONNEGATIVE_DISCOVERY_ROI',p_break,holdout),
        pack_rule('BEST_DISCOVERY_ROI_PROBABILITY_ONLY',p_best,holdout),
        pack_rule('BROADEST_NONNEGATIVE_DISCOVERY_ROI_PROBABILITY_PLUS_MARGIN',pm_break,holdout,True),
        pack_rule('BEST_DISCOVERY_ROI_PROBABILITY_PLUS_MARGIN',pm_best,holdout,True),
    ]
    oos_pass=[r for r in rules if r.get('state')=='OOS_PASS_POSITIVE_ROI']
    conclusion = 'OOS_POSITIVE_RULE_FOUND' if oos_pass else 'NO_OOS_PROFITABLE_THRESHOLD_FOUND'
    report={
        'version':VERSION,'generated_at':datetime.now(KST).isoformat(timespec='seconds'),
        'model_source':hv.MODEL_SOURCE,'input_races':len(races),'warmup_races':warmup,
        'odds_eligible_walk_forward_races':len(rows),
        'split':{'method':'CHRONOLOGICAL_60PCT_DISCOVERY_40PCT_UNTOUCHED_HOLDOUT','discovery_races':len(discovery),'holdout_races':len(holdout)},
        'stake_per_selected_race_krw':STAKE,'min_discovery_bets':MIN_DISCOVERY_BETS,'min_holdout_bets':MIN_HOLDOUT_BETS,
        'rules':rules,'conclusion':conclusion,
        'policy':'SELECTION_USES_PRE_RACE_MODEL_TOP_P_AND_MARGIN_ONLY; THRESHOLDS_CHOSEN_ON_EARLIER_DISCOVERY_PERIOD; PROFITABILITY_VERIFIED_ON_LATER_UNTOUCHED_HOLDOUT; OFFICIAL_FINAL_TOTE_ODDS_USED_ONLY_FOR SETTLEMENT; NO_POSTRACE_FIELD_IN_SELECTION; DO_NOT_PROMOTE DISCOVERY_ONLY PROFIT',
        'warning':'FINAL_TOTE_ODDS_ARE SETTLEMENT REFERENCE, NOT PRE-RACE LOCKED EXECUTION PRICES. POSITIVE HISTORICAL OOS ROI DOES NOT GUARANTEE FUTURE PROFIT.'
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'HORSE_WIN_CONFIDENCE_ROI':'PASS','conclusion':conclusion,'rows':len(rows),'rules':rules},ensure_ascii=False))

if __name__=='__main__': main()
