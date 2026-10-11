#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'data' / 'sports_today.json'
HISTORY = ROOT / 'data' / 'model_state' / 'sports_top3_performance.json'
KST = timezone(timedelta(hours=9))
SPORTS = ('SOCCER','BASEBALL','BASKETBALL','VOLLEYBALL')
VERSION = 'SPORTS_TOP3_PERFORMANCE_V1'
MIN_EVAL_FOR_ADVICE = 30
TARGET_HIT_RATE = 0.70


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


def _summary(records: dict):
    out = {'overall': {}, 'by_sport': {}}
    groups = {'overall': list(records.values())}
    for s in SPORTS:
        groups[s] = [r for r in records.values() if r.get('sport') == s]
    for key, rows in groups.items():
        ev = [r for r in rows if isinstance(r.get('evaluation'), dict) and isinstance(r['evaluation'].get('hit'), bool)]
        hits = sum(1 for r in ev if r['evaluation']['hit'])
        block = {
            'picks': len(rows), 'evaluated': len(ev), 'pending': len(rows)-len(ev),
            'hits': hits, 'misses': len(ev)-hits,
            'hit_rate': round(hits/len(ev), 6) if ev else None,
        }
        if key == 'overall': out['overall'] = block
        else: out['by_sport'][key] = block
    return out


def _threshold_advice(records: dict):
    advice = {}
    for sport in SPORTS:
        rows = [r for r in records.values() if r.get('sport') == sport and isinstance(r.get('evaluation'), dict) and isinstance(r['evaluation'].get('hit'), bool)]
        if len(rows) < MIN_EVAL_FOR_ADVICE:
            advice[sport] = {'state':'HOLD_SAMPLE', 'evaluated':len(rows), 'required':MIN_EVAL_FOR_ADVICE}
            continue
        hits = sum(1 for r in rows if r['evaluation']['hit'])
        rate = hits/len(rows)
        if rate < TARGET_HIT_RATE:
            action = 'TIGHTEN_REVIEW'
        elif rate >= 0.78:
            action = 'MAINTAIN_OR_CAUTIOUS_RELAX_REVIEW'
        else:
            action = 'MAINTAIN'
        advice[sport] = {'state':action, 'evaluated':len(rows), 'hits':hits, 'hit_rate':round(rate,6), 'target_hit_rate':TARGET_HIT_RATE}
    return advice


def apply(snapshot: dict, history: dict | None, now: datetime | None = None):
    now = now or datetime.now(KST)
    now_iso = now.isoformat(timespec='seconds')
    history = history if isinstance(history, dict) else {}
    records = history.setdefault('records', {})
    events = {str(e.get('id')): e for e in snapshot.get('events',[]) if e.get('id')}
    board = snapshot.get('sports_top3') or {}

    for sport in SPORTS:
        for row in (board.get('by_sport') or {}).get(sport, []) or []:
            eid = str(row.get('event_id') or '')
            if not eid:
                continue
            rec = records.get(eid) or {
                'event_id': eid,
                'date': board.get('date') or snapshot.get('date'),
                'sport': sport,
                'competition': row.get('competition'),
                'title': row.get('title'),
                'pick_key': row.get('pick_key'),
                'pick_name': row.get('pick_name'),
                'model_p': row.get('model_p'),
                'selection_score': row.get('selection_score'),
                'precision_gate': row.get('precision_gate'),
                'locked_at': row.get('locked_at'),
                'recorded_at': now_iso,
            }
            event = events.get(eid)
            if event:
                wk = _winner_key(event)
                if event.get('status') == 'FINAL' and wk:
                    rec['evaluation'] = {'winner_key':wk, 'hit':wk == rec.get('pick_key'), 'evaluated_at':now_iso}
            if isinstance(row.get('evaluation'), dict) and isinstance(row['evaluation'].get('hit'), bool):
                rec['evaluation'] = dict(row['evaluation']) | {'evaluated_at': now_iso}
            records[eid] = rec

    history['version'] = VERSION
    history['updated_at'] = now_iso
    history['summary'] = _summary(records)
    history['threshold_advice'] = _threshold_advice(records)
    history['policy'] = 'APPEND_ONLY_PICK_LEDGER; FINAL_RESULTS_UPDATE_HIT_MISS; THRESHOLD_ADVICE_REQUIRES_30_EVALUATED; ADVISORY_ONLY_NO_AUTOMATIC_GATE_MUTATION'
    return history


def run(snapshot_path: Path = SNAPSHOT, history_path: Path = HISTORY):
    snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
    history = None
    if history_path.exists():
        try: history = json.loads(history_path.read_text(encoding='utf-8'))
        except Exception: history = None
    out = apply(snapshot, history)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'SPORTS_TOP3_PERFORMANCE':'PASS','summary':out['summary'],'threshold_advice':out['threshold_advice']}, ensure_ascii=False))


def self_test():
    snap = {
        'date':'2026-10-12',
        'events':[{'id':'E1','sport':'BASKETBALL','status':'FINAL','result':{'home_score':110,'away_score':100}}],
        'sports_top3':{'date':'2026-10-12','by_sport':{'SOCCER':[],'BASEBALL':[],'BASKETBALL':[{'event_id':'E1','sport':'BASKETBALL','pick_key':'HOME','pick_name':'H','model_p':.76,'precision_gate':{'top_p':.76,'margin':.52}}],'VOLLEYBALL':[]}}
    }
    out = apply(snap, {}, datetime(2026,10,12,12,0,tzinfo=KST))
    assert out['summary']['overall']['evaluated'] == 1
    assert out['summary']['overall']['hits'] == 1
    assert out['summary']['by_sport']['BASKETBALL']['hit_rate'] == 1.0
    assert out['threshold_advice']['BASKETBALL']['state'] == 'HOLD_SAMPLE'
    print('SPORTS_TOP3_PERFORMANCE_SELF_TEST=PASS')


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    self_test() if a.self_test else run()

if __name__ == '__main__': main()
