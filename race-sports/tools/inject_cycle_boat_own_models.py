import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA = Path('race-sports/data/today.json')
HISTORY = Path('race-sports/data/history')
KST = timezone(timedelta(hours=9))

CONFIG = {
    'CYCLE': {
        'provider': 'CYCLE_OWN_MODEL',
        'source': 'cycle_empirical_bayes_v0.1',
        'official_source': 'KCYCLE_AI_OFFICIAL',
        'entity_strength': 14.0,
        'lane_strength': 28.0,
        'entity_weight': 0.78,
        'lane_weight': 0.22,
    },
    'BOAT': {
        'provider': 'BOAT_OWN_MODEL',
        'source': 'boat_empirical_bayes_v0.1',
        'official_source': 'KBOAT_AI_OFFICIAL',
        'entity_strength': 12.0,
        'lane_strength': 24.0,
        'entity_weight': 0.72,
        'lane_weight': 0.28,
    },
}


def now_text():
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')


def participant_name(o):
    s = str(o.get('name') or '').strip()
    s = re.sub(r'^\s*\d+\s*', '', s).strip()
    return s or None


def number_of(o):
    try:
        return int(o.get('number'))
    except Exception:
        m = re.match(r'\s*(\d+)', str(o.get('name') or ''))
        return int(m.group(1)) if m else None


def rank_of(e, o):
    try:
        return int(o.get('final_rank'))
    except Exception:
        pass
    for x in (e.get('result') or {}).get('top3') or []:
        try:
            if int(x.get('number')) == int(number_of(o)):
                return int(x.get('rank'))
        except Exception:
            pass
    return None


def history_docs(today_date):
    docs = []
    if not HISTORY.exists():
        return docs
    for p in sorted(HISTORY.glob('*.json')):
        try:
            d = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        if str(d.get('date') or '') > str(today_date or ''):
            continue
        docs.append(d)
    return docs


def build_stats(docs, sport):
    entity = defaultdict(lambda: [0, 0])
    lane = defaultdict(lambda: [0, 0])
    total_starts = total_wins = labeled_races = 0

    for d in docs:
        for e in d.get('events') or []:
            if e.get('sport') != sport or e.get('status') != 'FINAL':
                continue
            race_labeled = False
            for o in e.get('outcomes') or []:
                r = rank_of(e, o)
                if r is None:
                    continue
                race_labeled = True
                win = 1 if r == 1 else 0
                total_starts += 1
                total_wins += win
                name = participant_name(o)
                num = number_of(o)
                if name:
                    entity[name][0] += 1
                    entity[name][1] += win
                if num is not None:
                    lane[num][0] += 1
                    lane[num][1] += win
            if race_labeled:
                labeled_races += 1

    base = (total_wins / total_starts) if total_starts else (1.0 / (7.0 if sport == 'CYCLE' else 6.0))
    return entity, lane, base, total_starts, labeled_races


def posterior(pair, base, strength):
    starts, wins = pair if pair else (0, 0)
    return (wins + strength * base) / (starts + strength)


def logit(p):
    p = min(0.999, max(0.001, p))
    return math.log(p / (1.0 - p))


def prior_snapshot(doc, sport):
    out = {}
    date = str(doc.get('date') or '')
    p = HISTORY / f'{date}.json'
    if not p.exists():
        return out
    try:
        old = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return out
    for e in old.get('events') or []:
        if e.get('sport') != sport:
            continue
        eid = e.get('id')
        if not eid:
            continue
        for o in e.get('outcomes') or []:
            key = o.get('key') or f"N{number_of(o)}"
            if o.get('model_p') is None:
                continue
            out[(eid, key)] = {
                'model_p': o.get('model_p'),
                'model_source': o.get('model_source'),
                'model_updated_at': o.get('model_updated_at'),
                'model_state': o.get('model_state'),
                'model_validated': o.get('model_validated'),
                'official_ai_p': o.get('official_ai_p'),
                'official_ai_source': o.get('official_ai_source'),
            }
    return out


def score_race(e, entity, lane, base, cfg):
    outcomes = list(e.get('outcomes') or [])
    if not outcomes:
        return []
    scores = []
    for o in outcomes:
        ep = posterior(entity.get(participant_name(o)), base, cfg['entity_strength'])
        lp = posterior(lane.get(number_of(o)), base, cfg['lane_strength'])
        s = cfg['entity_weight'] * logit(ep) + cfg['lane_weight'] * logit(lp)
        scores.append(s)
    m = max(scores)
    ex = [math.exp(x - m) for x in scores]
    den = sum(ex) or 1.0
    return [x / den for x in ex]


def set_provider(doc, sport, status, rows, labeled_runners, labeled_races):
    cfg = CONFIG[sport]
    providers = doc.setdefault('providers', [])
    providers[:] = [x for x in providers if x.get('provider') != cfg['provider']]
    providers.append({
        'provider': cfg['provider'],
        'status': status,
        'rows': rows,
        'model_source': cfg['source'],
        'model_validated': False,
        'model_state': 'PROVISIONAL_UNVALIDATED',
        'value_enabled': False,
        'history_labeled_runners': labeled_runners,
        'history_labeled_races': labeled_races,
        'official_ai_preserved': True,
        'updated_at': datetime.now(KST).isoformat(timespec='seconds'),
    })


def apply_sport(doc, sport):
    cfg = CONFIG[sport]
    docs = history_docs(doc.get('date'))
    entity, lane, base, labeled_runners, labeled_races = build_stats(docs, sport)
    prior = prior_snapshot(doc, sport)
    updated = 0
    events = 0

    for e in doc.get('events') or []:
        if e.get('sport') != sport:
            continue
        events += 1
        outcomes = e.get('outcomes') or []
        status = e.get('status')

        if status == 'SCHEDULED':
            probs = score_race(e, entity, lane, base, cfg)
            if len(probs) != len(outcomes) or not probs:
                continue
            for o, p in zip(outcomes, probs):
                if o.get('model_source') == cfg['official_source'] and o.get('model_p') is not None:
                    o['official_ai_p'] = o.get('model_p')
                    o['official_ai_source'] = cfg['official_source']
                o['model_p'] = round(float(p), 8)
                o['model_source'] = cfg['source']
                o['model_updated_at'] = now_text()
                o['model_state'] = 'PROVISIONAL_UNVALIDATED'
                o['model_validated'] = False
                updated += 1
            e['model_source'] = cfg['source']
            e['model_state'] = 'PROVISIONAL_UNVALIDATED'
            e['model_validated'] = False
            e['value_enabled'] = False

        else:
            eid = e.get('id')
            carried = 0
            for o in outcomes:
                key = o.get('key') or f"N{number_of(o)}"
                old = prior.get((eid, key))
                if not old:
                    continue
                for k, v in old.items():
                    if v is not None:
                        o[k] = v
                carried += 1
            if carried:
                e['model_source'] = cfg['source']
                e['model_state'] = 'PROVISIONAL_UNVALIDATED'
                e['model_validated'] = False
                e['value_enabled'] = False

    status = 'PROVISIONAL' if events else 'NO_TODAY_CARD'
    set_provider(doc, sport, status, updated, labeled_runners, labeled_races)
    return updated, events, labeled_runners, labeled_races


def self_test():
    for sport, n in [('CYCLE', 7), ('BOAT', 6)]:
        doc = {
            'date': '2099-01-01',
            'events': [{
                'id': f'{sport}-TEST-1', 'sport': sport, 'status': 'SCHEDULED',
                'outcomes': [
                    {'key': f'N{i}', 'number': i, 'name': f'{i} 선수{i}', 'model_p': 1.0 / n, 'model_source': CONFIG[sport]['official_source']}
                    for i in range(1, n + 1)
                ]
            }],
            'providers': []
        }
        updated, events, _, _ = apply_sport(doc, sport)
        vals = [o['model_p'] for o in doc['events'][0]['outcomes']]
        assert events == 1 and updated == n
        assert abs(sum(vals) - 1.0) < 1e-6, (sport, vals, sum(vals))
        assert all(0.0 <= x <= 1.0 for x in vals)
        assert all(o.get('official_ai_p') is not None for o in doc['events'][0]['outcomes'])
        assert doc['events'][0]['model_validated'] is False
    print('CYCLE_BOAT_OWN_MODEL_SELF_TEST=PASS')


def main():
    if '--self-test' in sys.argv:
        self_test()
        return
    doc = json.loads(DATA.read_text(encoding='utf-8'))
    for sport in ('CYCLE', 'BOAT'):
        updated, events, labeled_runners, labeled_races = apply_sport(doc, sport)
        print(f'{sport}_OWN_MODEL={"PROVISIONAL" if events else "NO_TODAY_CARD"}')
        print(f'{sport}_OWN_MODEL_ROWS={updated}')
        print(f'{sport}_HISTORY_LABELED_RUNNERS={labeled_runners}')
        print(f'{sport}_HISTORY_LABELED_RACES={labeled_races}')
        print(f'{sport}_VALUE_ENABLED=FALSE')
    DATA.write_text(json.dumps(doc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


if __name__ == '__main__':
    main()
