#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'data' / 'sports_today.json'
HISTORY = ROOT / 'data' / 'model_state' / 'sports_top3_performance.json'
SPORTS_HISTORY = ROOT / 'data' / 'sports_history'
KST = timezone(timedelta(hours=9))
SPORTS = ('SOCCER','BASEBALL','BASKETBALL','VOLLEYBALL')
VERSION = 'SPORTS_TOP3_PERFORMANCE_V4_LOCKED_ODDS_PAPER_ROI'
MIN_EVAL_FOR_ADVICE = 30
TARGET_HIT_RATE = 0.70
CARRYOVER_DAYS = 3
PAPER_STAKE_KRW = 100_000


def _f(v, default=None):
    try:
        x=float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _winner_key(event: dict):
    r = event.get('result') or {}
    wk = r.get('winner_key')
    if wk in {'HOME','AWAY','DRAW'}:
        return wk
    try:
        hs, aw = float(r['home_score']), float(r['away_score'])
    except Exception:
        return None
    if hs > aw: return 'HOME'
    if aw > hs: return 'AWAY'
    return 'DRAW' if event.get('sport') == 'SOCCER' else None


def _is_final(event: dict) -> bool:
    return str(event.get('status') or '').upper() == 'FINAL' and _winner_key(event) is not None


def _paper_summary(rows):
    eligible=[r for r in rows if _f(r.get('locked_odds')) is not None and _f(r.get('locked_odds')) > 1]
    settled=[r for r in eligible if isinstance((r.get('virtual_bet') or {}).get('profit_krw'), (int,float))]
    pending=len(eligible)-len(settled)
    stake=sum(int((r.get('virtual_bet') or {}).get('stake_krw') or PAPER_STAKE_KRW) for r in settled)
    returned=sum(float((r.get('virtual_bet') or {}).get('return_krw') or 0) for r in settled)
    profit=sum(float((r.get('virtual_bet') or {}).get('profit_krw') or 0) for r in settled)
    return {
        'stake_per_pick_krw':PAPER_STAKE_KRW,
        'odds_locked_picks':len(eligible),
        'settled':len(settled),
        'pending':pending,
        'excluded_no_locked_odds':len(rows)-len(eligible),
        'total_staked_krw':int(round(stake)),
        'total_return_krw':int(round(returned)),
        'net_profit_krw':int(round(profit)),
        'roi':round(profit/stake,6) if stake else None,
    }


def _summary(records: dict):
    out = {'overall': {}, 'by_sport': {}}
    groups = {'overall': list(records.values())}
    for s in SPORTS:
        groups[s] = [r for r in records.values() if r.get('sport') == s]
    for key, rows in groups.items():
        ev = [r for r in rows if isinstance(r.get('evaluation'), dict) and isinstance(r['evaluation'].get('hit'), bool)]
        hits = sum(1 for r in ev if r['evaluation']['hit'])
        block = {'picks':len(rows),'evaluated':len(ev),'pending':len(rows)-len(ev),'hits':hits,'misses':len(ev)-hits,'hit_rate':round(hits/len(ev),6) if ev else None,'paper_roi':_paper_summary(rows)}
        if key == 'overall': out['overall'] = block
        else: out['by_sport'][key] = block
    return out


def _threshold_advice(records: dict):
    advice = {}
    for sport in SPORTS:
        rows = [r for r in records.values() if r.get('sport') == sport and isinstance(r.get('evaluation'), dict) and isinstance(r['evaluation'].get('hit'), bool)]
        if len(rows) < MIN_EVAL_FOR_ADVICE:
            advice[sport] = {'state':'HOLD_SAMPLE','evaluated':len(rows),'required':MIN_EVAL_FOR_ADVICE}; continue
        hits = sum(1 for r in rows if r['evaluation']['hit']); rate = hits/len(rows)
        action = 'TIGHTEN_REVIEW' if rate < TARGET_HIT_RATE else 'MAINTAIN_OR_CAUTIOUS_RELAX_REVIEW' if rate >= 0.78 else 'MAINTAIN'
        advice[sport] = {'state':action,'evaluated':len(rows),'hits':hits,'hit_rate':round(rate,6),'target_hit_rate':TARGET_HIT_RATE}
    return advice


def _recent(records: dict, limit: int = 8):
    rows = list(records.values()); rows.sort(key=lambda r:(str(r.get('date') or ''),str(r.get('recorded_at') or '')), reverse=True)
    out=[]
    for r in rows[:limit]:
        item={k:r.get(k) for k in ('event_id','date','sport','competition','title','pick_key','pick_name','model_p','locked_odds','locked_odds_provider','resolution_state')}
        if isinstance(r.get('evaluation'),dict): item['evaluation']={k:r['evaluation'].get(k) for k in ('winner_key','hit','evaluated_at','source','source_snapshot_date')}
        if isinstance(r.get('virtual_bet'),dict): item['virtual_bet']=dict(r['virtual_bet'])
        out.append(item)
    return out


def _public_block(history: dict):
    return {'version':history.get('version'),'updated_at':history.get('updated_at'),'summary':history.get('summary') or {},'threshold_advice':history.get('threshold_advice') or {},'recent':_recent(history.get('records') or {}),'carryover':history.get('carryover') or {},'paper_betting_policy':history.get('paper_betting_policy') or {},'sample_rule':{'min_evaluated_per_sport':MIN_EVAL_FOR_ADVICE,'target_hit_rate':TARGET_HIT_RATE}}


def _parse_day(v):
    try: return date.fromisoformat(str(v)[:10])
    except Exception: return None


def _candidate_days(day_value):
    d=_parse_day(day_value)
    if not d: return []
    return [(d+timedelta(days=i)).isoformat() for i in range(CARRYOVER_DAYS+1)]


def _load_history_snapshots(records: dict, history_dir: Path):
    wanted=set()
    for r in records.values():
        if not (isinstance(r.get('evaluation'),dict) and isinstance(r['evaluation'].get('hit'),bool)):
            wanted.update(_candidate_days(r.get('date')))
    out=[]
    for day in sorted(wanted):
        p=history_dir / f'{day}.json'
        if not p.exists(): continue
        try:
            snap=json.loads(p.read_text(encoding='utf-8'))
            if isinstance(snap,dict): out.append((day,snap))
        except Exception:
            continue
    return out


def _resolve_pending(records: dict, snapshots: list[tuple[str,dict]], now: datetime):
    resolved=0; conflicts=0; still_pending=0; aged=0
    index={}
    for snap_day,snap in snapshots:
        for e in snap.get('events',[]) or []:
            eid=str(e.get('id') or '')
            if eid: index.setdefault(eid,[]).append((snap_day,e))
    for eid,rec in records.items():
        if isinstance(rec.get('evaluation'),dict) and isinstance(rec['evaluation'].get('hit'),bool): continue
        finals=[]
        for snap_day,e in index.get(str(eid),[]):
            if _is_final(e): finals.append((snap_day,_winner_key(e),e))
        winners={x[1] for x in finals}
        if len(winners)>1:
            rec['resolution_state']='RESULT_CONFLICT_FAIL_CLOSED'; rec['resolution_conflict_winners']=sorted(winners); conflicts+=1; continue
        if len(winners)==1:
            snap_day,wk,e=sorted(finals,key=lambda x:x[0])[-1]
            rec['evaluation']={'winner_key':wk,'hit':wk==rec.get('pick_key'),'evaluated_at':now.isoformat(timespec='seconds'),'source':'SPORTS_HISTORY_CARRYOVER','source_snapshot_date':snap_day}
            rec['resolution_state']='RESOLVED_FROM_HISTORY'
            r=e.get('result') or {}
            if 'home_score' in r: rec['final_home_score']=r.get('home_score')
            if 'away_score' in r: rec['final_away_score']=r.get('away_score')
            resolved+=1; continue
        d=_parse_day(rec.get('date'))
        if d and (now.date()-d).days > CARRYOVER_DAYS:
            rec['resolution_state']='UNRESOLVED_AFTER_HISTORY_WINDOW'; aged+=1
        else:
            rec['resolution_state']='PENDING_RESULT'; still_pending+=1
    return {'resolved_from_history':resolved,'conflicts':conflicts,'pending_within_window':still_pending,'unresolved_after_window':aged,'window_days':CARRYOVER_DAYS}


def _settle_virtual_bets(records: dict, now_iso: str):
    for rec in records.values():
        odds=_f(rec.get('locked_odds'))
        if odds is None or odds <= 1:
            rec['virtual_bet']={'state':'EXCLUDED_NO_LOCKED_ODDS','stake_krw':PAPER_STAKE_KRW}
            continue
        vb=rec.get('virtual_bet') if isinstance(rec.get('virtual_bet'),dict) else {}
        vb.update({'state':'PENDING_RESULT','stake_krw':PAPER_STAKE_KRW,'locked_decimal_odds':round(odds,6),'odds_provider':rec.get('locked_odds_provider')})
        ev=rec.get('evaluation') if isinstance(rec.get('evaluation'),dict) else None
        if ev and isinstance(ev.get('hit'),bool):
            ret=PAPER_STAKE_KRW*odds if ev['hit'] else 0.0
            vb.update({'state':'SETTLED','hit':ev['hit'],'return_krw':int(round(ret)),'profit_krw':int(round(ret-PAPER_STAKE_KRW)),'settled_at':ev.get('evaluated_at') or now_iso})
        rec['virtual_bet']=vb


def apply(snapshot: dict, history: dict | None, now: datetime | None = None, history_snapshots: list[tuple[str,dict]] | None = None):
    now = now or datetime.now(KST); now_iso=now.isoformat(timespec='seconds')
    history = history if isinstance(history,dict) else {}; records=history.setdefault('records',{})
    events={str(e.get('id')):e for e in snapshot.get('events',[]) if e.get('id')}; board=snapshot.get('sports_top3') or {}
    for sport in SPORTS:
        for row in (board.get('by_sport') or {}).get(sport,[]) or []:
            eid=str(row.get('event_id') or '')
            if not eid: continue
            event=events.get(eid)
            rec=records.get(eid)
            if rec is None:
                rec={'event_id':eid,'date':board.get('date') or snapshot.get('date'),'sport':sport,'competition':row.get('competition'),'title':row.get('title'),'pick_key':row.get('pick_key'),'pick_name':row.get('pick_name'),'model_p':row.get('model_p'),'selection_score':row.get('selection_score'),'precision_gate':row.get('precision_gate'),'locked_at':row.get('locked_at'),'recorded_at':now_iso}
                odds=_f(row.get('odds'))
                if odds is not None and odds > 1:
                    rec['locked_odds']=round(odds,6)
                    rec['locked_odds_provider']=row.get('odds_provider')
                    rec['odds_locked_at']=row.get('locked_at') or now_iso
            if event:
                for k in ('provider','provider_event_id','source_url','event_date','start_time','start_timestamp','home','away','home_ko','away_ko'):
                    if event.get(k) is not None: rec.setdefault(k,event.get(k))
                wk=_winner_key(event)
                if _is_final(event) and wk:
                    rec['evaluation']={'winner_key':wk,'hit':wk==rec.get('pick_key'),'evaluated_at':now_iso,'source':'CURRENT_SNAPSHOT','source_snapshot_date':snapshot.get('date')}; rec['resolution_state']='RESOLVED_CURRENT'
            if isinstance(row.get('evaluation'),dict) and isinstance(row['evaluation'].get('hit'),bool):
                rec['evaluation']=dict(row['evaluation']) | {'evaluated_at':now_iso,'source':row['evaluation'].get('source') or 'LOCKED_BOARD','source_snapshot_date':snapshot.get('date')}; rec['resolution_state']='RESOLVED_BOARD'
            records[eid]=rec
    snapshots=list(history_snapshots or [])
    snapshots.append((str(snapshot.get('date') or now.date().isoformat()),snapshot))
    carry=_resolve_pending(records,snapshots,now)
    _settle_virtual_bets(records,now_iso)
    history['version']=VERSION; history['updated_at']=now_iso; history['summary']=_summary(records); history['threshold_advice']=_threshold_advice(records); history['carryover']=carry
    history['paper_betting_policy']={'mode':'PAPER_ONLY','stake_per_pick_krw':PAPER_STAKE_KRW,'odds_rule':'LOCK_DECIMAL_ODDS_AT_FIRST_TOP3_RECORD_CREATION_ONLY','missing_odds_rule':'EXCLUDE_FROM_ROI_NEVER_BACKFILL_RETROACTIVELY','settlement_rule':'WIN=STAKE*LOCKED_ODDS; LOSS=0_RETURN; PROFIT=RETURN-STAKE','real_betting':False}
    history['policy']='APPEND_ONLY_PICK_LEDGER; CURRENT_AND_SPORTS_HISTORY_FINAL_RESULTS_RESOLVE_PENDING; HISTORY_WINDOW_3_DAYS; CONFLICT_FAIL_CLOSED; NEVER_COUNT_UNRESOLVED_AS_MISS; LOCK_ODDS_ON_FIRST_RECORD_ONLY; NO_RETROACTIVE_ODDS; PAPER_100K_FIXED_STAKE; THRESHOLD_ADVICE_REQUIRES_30_EVALUATED'
    return history


def run(snapshot_path: Path = SNAPSHOT, history_path: Path = HISTORY, sports_history_dir: Path = SPORTS_HISTORY):
    snapshot=json.loads(snapshot_path.read_text(encoding='utf-8')); history=None
    if history_path.exists():
        try: history=json.loads(history_path.read_text(encoding='utf-8'))
        except Exception: history=None
    base=history if isinstance(history,dict) else {}
    history_snapshots=_load_history_snapshots(base.get('records') or {},sports_history_dir)
    out=apply(snapshot,history,history_snapshots=history_snapshots)
    board=snapshot.setdefault('sports_top3',{}); board['performance']=_public_block(out)
    history_path.parent.mkdir(parents=True,exist_ok=True); history_path.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); snapshot_path.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'SPORTS_TOP3_PERFORMANCE':'PASS','summary':out['summary'],'carryover':out['carryover'],'threshold_advice':out['threshold_advice'],'paper_betting_policy':out['paper_betting_policy'],'public_snapshot':True},ensure_ascii=False))


def self_test():
    now=datetime(2026,10,13,12,0,tzinfo=KST)
    history={'records':{'OLD':{'event_id':'OLD','date':'2026-10-12','sport':'BASKETBALL','pick_key':'HOME','recorded_at':'2026-10-12T20:00:00+09:00'}}}
    snap={'date':'2026-10-13','events':[{'id':'NEW','sport':'BASKETBALL','status':'FINAL','result':{'home_score':110,'away_score':100,'winner_key':'HOME'}}],'sports_top3':{'date':'2026-10-13','by_sport':{s:([{'event_id':'NEW','sport':'BASKETBALL','competition':'NBA','title':'H vs A','pick_key':'HOME','pick_name':'H','model_p':.75,'odds':1.8,'odds_provider':'TESTBOOK','locked_at':'2026-10-13T10:00:00+09:00'}] if s=='BASKETBALL' else []) for s in SPORTS}}}
    hist_snap={'date':'2026-10-12','events':[{'id':'OLD','sport':'BASKETBALL','status':'FINAL','result':{'home_score':110,'away_score':100,'winner_key':'HOME'}}]}
    out=apply(snap,history,now,[('2026-10-12',hist_snap)]); pub=_public_block(out)
    assert out['summary']['overall']['evaluated']==2 and out['summary']['overall']['hits']==2
    assert out['records']['OLD']['evaluation']['source']=='SPORTS_HISTORY_CARRYOVER'
    assert out['records']['OLD']['virtual_bet']['state']=='EXCLUDED_NO_LOCKED_ODDS'
    assert out['records']['NEW']['locked_odds']==1.8
    assert out['records']['NEW']['virtual_bet']['profit_krw']==80000
    assert out['summary']['overall']['paper_roi']['total_staked_krw']==100000
    assert out['summary']['overall']['paper_roi']['net_profit_krw']==80000
    assert out['summary']['overall']['paper_roi']['roi']==0.8
    conflict={'date':'2026-10-13','events':[{'id':'X','sport':'SOCCER','status':'FINAL','result':{'winner_key':'HOME'}},{'id':'X','sport':'SOCCER','status':'FINAL','result':{'winner_key':'AWAY'}}]}
    h2={'records':{'X':{'event_id':'X','date':'2026-10-13','sport':'SOCCER','pick_key':'HOME'}}}
    o2=apply({'date':'2026-10-13','events':[],'sports_top3':{'date':'2026-10-13','by_sport':{s:[] for s in SPORTS}}},h2,now,[('2026-10-13',conflict)])
    assert 'evaluation' not in o2['records']['X'] and o2['records']['X']['resolution_state']=='RESULT_CONFLICT_FAIL_CLOSED'
    assert pub['sample_rule']['min_evaluated_per_sport']==30
    print('SPORTS_TOP3_PERFORMANCE_SELF_TEST=PASS')


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args(); self_test() if a.self_test else run()

if __name__=='__main__': main()
