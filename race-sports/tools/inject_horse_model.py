import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA = Path('race-sports/data/today.json')
HISTORY = Path('race-sports/data/history')
KST = timezone(timedelta(hours=9))
MODEL_SOURCE = 'horse_empirical_bayes_v0.1'
PROVIDER = 'HORSE_MODEL'


def now_text():
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')


def safe_float(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def entity_key(o, field):
    v = o.get(field)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def rank_of(e, o):
    r = o.get('final_rank')
    try:
        return int(r)
    except Exception:
        pass
    result = e.get('result') or {}
    for x in result.get('top3') or []:
        try:
            if int(x.get('number')) == int(o.get('number')):
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


def build_stats(docs):
    stats = {
        'horse': defaultdict(lambda: [0, 0]),
        'jockey': defaultdict(lambda: [0, 0]),
        'trainer': defaultdict(lambda: [0, 0]),
    }
    total_starts = 0
    total_wins = 0
    labeled_races = 0
    for d in docs:
        for e in d.get('events') or []:
            if e.get('sport') != 'HORSE' or e.get('status') != 'FINAL':
                continue
            race_labeled = False
            for o in e.get('outcomes') or []:
                r = rank_of(e, o)
                if r is None:
                    continue
                race_labeled = True
                total_starts += 1
                win = 1 if r == 1 else 0
                total_wins += win
                for bucket, field in [('horse', 'horse_name'), ('jockey', 'jockey'), ('trainer', 'trainer')]:
                    k = entity_key(o, field)
                    if not k:
                        continue
                    stats[bucket][k][0] += 1
                    stats[bucket][k][1] += win
            if race_labeled:
                labeled_races += 1
    base = (total_wins / total_starts) if total_starts else 0.10
    return stats, base, total_starts, labeled_races


def posterior(pair, base, strength):
    starts, wins = pair if pair else (0, 0)
    return (wins + strength * base) / (starts + strength)


def logit(p):
    p = min(0.999, max(0.001, p))
    return math.log(p / (1.0 - p))


def prior_snapshot(doc):
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
        if e.get('sport') != 'HORSE':
            continue
        eid = e.get('id')
        if not eid:
            continue
        for o in e.get('outcomes') or []:
            key = o.get('key') or f"N{o.get('number')}"
            if o.get('model_p') is None:
                continue
            out[(eid, key)] = {
                'model_p': o.get('model_p'),
                'model_source': o.get('model_source'),
                'model_updated_at': o.get('model_updated_at'),
                'model_state': o.get('model_state'),
                'model_validated': o.get('model_validated'),
            }
    return out


def score_race(e, stats, base):
    outcomes = list(e.get('outcomes') or [])
    if not outcomes:
        return []
    weights = [safe_float(o.get('assigned_weight')) for o in outcomes]
    valid_w = [x for x in weights if x is not None]
    mean_w = sum(valid_w) / len(valid_w) if valid_w else 0.0
    var_w = sum((x - mean_w) ** 2 for x in valid_w) / len(valid_w) if valid_w else 0.0
    sd_w = math.sqrt(var_w) if var_w > 1e-9 else 1.0

    scores = []
    for i, o in enumerate(outcomes):
        hp = posterior(stats['horse'].get(entity_key(o, 'horse_name')), base, 10.0)
        jp = posterior(stats['jockey'].get(entity_key(o, 'jockey')), base, 18.0)
        tp = posterior(stats['trainer'].get(entity_key(o, 'trainer')), base, 18.0)
        s = 0.50 * logit(hp) + 0.28 * logit(jp) + 0.22 * logit(tp)

        age = safe_float(o.get('age'))
        if age is not None:
            s -= 0.035 * abs(age - 4.0)

        w = weights[i]
        if w is not None and valid_w:
            s -= 0.06 * ((w - mean_w) / sd_w)

        scores.append(s)

    m = max(scores)
    ex = [math.exp(x - m) for x in scores]
    den = sum(ex) or 1.0
    return [x / den for x in ex]


def set_provider(doc, status, rows, labeled_runners, labeled_races):
    providers = doc.setdefault('providers', [])
    providers[:] = [x for x in providers if x.get('provider') != PROVIDER]
    providers.append({
        'provider': PROVIDER,
        'status': status,
        'rows': rows,
        'model_source': MODEL_SOURCE,
        'model_validated': False,
        'model_state': 'PROVISIONAL_UNVALIDATED',
        'value_enabled': False,
        'history_labeled_runners': labeled_runners,
        'history_labeled_races': labeled_races,
        'updated_at': datetime.now(KST).isoformat(timespec='seconds'),
    })


def apply(doc):
    docs = history_docs(doc.get('date'))
    stats, base, labeled_runners, labeled_races = build_stats(docs)
    prior = prior_snapshot(doc)
    updated = 0
    horse_events = 0

    for e in doc.get('events') or []:
        if e.get('sport') != 'HORSE':
            continue
        horse_events += 1
        outcomes = e.get('outcomes') or []
        status = e.get('status')

        if status == 'SCHEDULED':
            probs = score_race(e, stats, base)
            if len(probs) != len(outcomes) or not probs:
                continue
            for o, p in zip(outcomes, probs):
                o['model_p'] = round(float(p), 8)
                o['model_source'] = MODEL_SOURCE
                o['model_updated_at'] = now_text()
                o['model_state'] = 'PROVISIONAL_UNVALIDATED'
                o['model_validated'] = False
                updated += 1
            e['model_source'] = MODEL_SOURCE
            e['model_state'] = 'PROVISIONAL_UNVALIDATED'
            e['model_validated'] = False
            e['value_enabled'] = False

        else:
            eid = e.get('id')
            carried = 0
            for o in outcomes:
                key = o.get('key') or f"N{o.get('number')}"
                old = prior.get((eid, key))
                if not old:
                    continue
                for k, v in old.items():
                    if v is not None:
                        o[k] = v
                carried += 1
            if carried:
                e['model_source'] = MODEL_SOURCE
                e['model_state'] = 'PROVISIONAL_UNVALIDATED'
                e['model_validated'] = False
                e['value_enabled'] = False

    status = 'PROVISIONAL' if horse_events else 'NO_TODAY_CARD'
    set_provider(doc, status, updated, labeled_runners, labeled_races)
    return updated, horse_events, labeled_runners, labeled_races


def self_test():
    doc = {
        'date': '2099-01-01',
        'events': [{
            'id': 'HORSE-TEST-1', 'sport': 'HORSE', 'status': 'SCHEDULED',
            'outcomes': [
                {'key': 'N1', 'number': 1, 'horse_name': 'A', 'jockey': 'J1', 'trainer': 'T1', 'age': 3, 'assigned_weight': 54.0},
                {'key': 'N2', 'number': 2, 'horse_name': 'B', 'jockey': 'J2', 'trainer': 'T2', 'age': 5, 'assigned_weight': 57.0},
                {'key': 'N3', 'number': 3, 'horse_name': 'C', 'jockey': 'J3', 'trainer': 'T3', 'age': 4, 'assigned_weight': 55.0},
            ]
        }],
        'providers': []
    }
    updated, _, _, _ = apply(doc)
    vals = [o['model_p'] for o in doc['events'][0]['outcomes']]
    assert updated == 3
    assert abs(sum(vals) - 1.0) < 1e-6, vals
    assert all(0.0 <= x <= 1.0 for x in vals)
    assert doc['events'][0]['model_validated'] is False
    print('HORSE_MODEL_SELF_TEST=PASS')


def main():
    if '--self-test' in sys.argv:
        self_test()
        return
    doc = json.loads(DATA.read_text(encoding='utf-8'))
    updated, horse_events, labeled_runners, labeled_races = apply(doc)
    DATA.write_text(json.dumps(doc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'HORSE_MODEL={"PROVISIONAL" if horse_events else "NO_TODAY_CARD"}')
    print(f'HORSE_MODEL_ROWS={updated}')
    print(f'HORSE_HISTORY_LABELED_RUNNERS={labeled_runners}')
    print(f'HORSE_HISTORY_LABELED_RACES={labeled_races}')
    print('HORSE_VALUE_ENABLED=FALSE')


if __name__ == '__main__':
    main()
