import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA = Path('race-sports/data/today.json')
HISTORY = Path('race-sports/data/history')
BACKFILL = Path('race-sports/data/backfill')
STATE = Path('race-sports/data/model_state/cycle_boat_own_predictions.json')
MODELS = Path('race-sports/models')
KST = timezone(timedelta(hours=9))

CONFIG = {
    'CYCLE': {
        'provider': 'CYCLE_OWN_MODEL',
        'source': 'cycle_hybrid_bayes_v0.2',
        'official_source': 'KCYCLE_AI_OFFICIAL',
        'entity_strength': 14.0,
        'lane_strength': 28.0,
        'entity_weight': 0.78,
        'lane_weight': 0.22,
        'full_own_races': 250.0,
        'min_own_races_without_seed': 50,
    },
    'BOAT': {
        'provider': 'BOAT_OWN_MODEL',
        'source': 'boat_hybrid_bayes_v0.2',
        'official_source': 'KBOAT_AI_OFFICIAL',
        'entity_strength': 12.0,
        'lane_strength': 24.0,
        'entity_weight': 0.72,
        'lane_weight': 0.28,
        'full_own_races': 200.0,
        'min_own_races_without_seed': 40,
    },
}


def now_text():
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')


def safe_float(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def participant_name(o):
    s = str(o.get('rider_name') or o.get('racer_name') or o.get('name') or '').strip()
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


def winner_number(e):
    for x in (e.get('result') or {}).get('top3') or []:
        try:
            if int(x.get('rank')) == 1:
                return int(x.get('number'))
        except Exception:
            pass
    return None


def norm_person_name(v):
    s = re.sub(r'^\s*\d+\s*', '', str(v or '')).strip()
    return re.sub(r'\s+', '', s)


def cycle_result_matches_card(e):
    if e.get('sport') != 'CYCLE':
        return True
    outs = {number_of(o): norm_person_name(participant_name(o)) for o in (e.get('outcomes') or [])}
    top3 = (e.get('result') or {}).get('top3') or []
    if not top3:
        return False
    for x in top3:
        try:
            n = int(x.get('number'))
        except Exception:
            return False
        result_name = norm_person_name(x.get('name'))
        if n not in outs or not outs[n] or not result_name or outs[n] != result_name:
            return False
    return True


def win_label(e, o):
    # FINAL result pages often publish only top-3 ranks. When the official
    # result is confirmed, every other listed starter is still a valid loser.
    if o.get('won') is True:
        return 1
    if o.get('won') is False:
        return 0
    r = rank_of(e, o)
    if r is not None:
        return 1 if r == 1 else 0
    wn = winner_number(e)
    n = number_of(o)
    if (e.get('result') or {}).get('status') == 'CONFIRMED' and wn is not None and n is not None:
        return 1 if n == wn else 0
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


def iter_backfill(sport):
    d = BACKFILL / sport.lower()
    if not d.exists():
        return
    for p in sorted(d.glob('*.jsonl')):
        try:
            with p.open('r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if e.get('sport') == sport and e.get('status') == 'FINAL':
                        yield e
        except Exception:
            continue


def build_stats(docs, sport):
    entity = defaultdict(lambda: [0, 0])
    lane = defaultdict(lambda: [0, 0])
    total_starts = total_wins = labeled_races = 0
    seen = set()

    def consume(e):
        nonlocal total_starts, total_wins, labeled_races
        if sport == 'CYCLE' and not cycle_result_matches_card(e):
            return
        outcomes=list(e.get('outcomes') or [])
        labels=[win_label(e,o) for o in outcomes]
        if not outcomes or any(x is None for x in labels) or sum(labels) != 1:
            return
        if e.get('id'):
            seen.add(e.get('id'))
        for o, win in zip(outcomes, labels):
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
        labeled_races += 1

    for e in iter_backfill(sport) or []:
        consume(e)

    for d in docs:
        for e in d.get('events') or []:
            if e.get('sport') != sport or e.get('status') != 'FINAL':
                continue
            if e.get('id') and e.get('id') in seen:
                continue
            consume(e)

    base = (total_wins / total_starts) if total_starts else (1.0 / (7.0 if sport == 'CYCLE' else 6.0))
    return entity, lane, base, total_starts, labeled_races


def posterior(pair, base, strength):
    starts, wins = pair if pair else (0, 0)
    return (wins + strength * base) / (starts + strength)


def logit(p):
    p = min(0.999, max(0.001, p))
    return math.log(p / (1.0 - p))


def normalize(vals):
    vals = [max(0.0, float(x)) for x in vals]
    s = sum(vals)
    if s <= 0:
        return []
    return [x / s for x in vals]


def empirical_probs(outcomes, entity, lane, base, cfg):
    scores = []
    for o in outcomes:
        ep = posterior(entity.get(participant_name(o)), base, cfg['entity_strength'])
        lp = posterior(lane.get(number_of(o)), base, cfg['lane_strength'])
        scores.append(cfg['entity_weight'] * logit(ep) + cfg['lane_weight'] * logit(lp))
    if not scores:
        return []
    m = max(scores)
    return normalize([math.exp(x - m) for x in scores])


def official_seed(outcomes, cfg):
    vals = []
    for o in outcomes:
        p = None
        if o.get('model_source') == cfg['official_source']:
            p = safe_float(o.get('model_p'))
        elif o.get('official_ai_source') == cfg['official_source']:
            p = safe_float(o.get('official_ai_p'))
        if p is None or p <= 0:
            return None
        vals.append(p)
    vals = normalize(vals)
    return vals if len(vals) == len(outcomes) else None


def score_race(e, entity, lane, base, labeled_races, cfg):
    outcomes = list(e.get('outcomes') or [])
    if not outcomes:
        return [], 0.0, False
    empirical = empirical_probs(outcomes, entity, lane, base, cfg)
    if not empirical:
        return [], 0.0, False
    seed = official_seed(outcomes, cfg)
    history_weight = min(1.0, max(0.0, labeled_races / cfg['full_own_races']))
    if not seed:
        if labeled_races < cfg['min_own_races_without_seed']:
            return [], history_weight, False
        return empirical, history_weight, False
    blended = [((1.0 - history_weight) * a) + (history_weight * b) for a, b in zip(seed, empirical)]
    return normalize(blended), history_weight, True


def load_state():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text(encoding='utf-8'))
            if isinstance(d, dict) and isinstance(d.get('predictions'), dict):
                return d
        except Exception:
            pass
    return {'version': 2, 'predictions': {}}


def state_key(e, o):
    return f"{e.get('id')}|{o.get('key') or f'N{number_of(o)}'}"


def save_prediction(state, doc, sport, e, o):
    state['predictions'][state_key(e, o)] = {
        'date': str(doc.get('date') or ''),
        'sport': sport,
        'model_p': o.get('model_p'),
        'model_source': o.get('model_source'),
        'model_updated_at': o.get('model_updated_at'),
        'model_state': o.get('model_state'),
        'model_validated': o.get('model_validated'),
        'official_ai_p': o.get('official_ai_p'),
        'official_ai_source': o.get('official_ai_source'),
        'own_history_weight': o.get('own_history_weight'),
        'official_seed_used': o.get('official_seed_used'),
    }


def trim_state(state, today_text, keep_days=90):
    try:
        cutoff = (datetime.strptime(today_text, '%Y-%m-%d') - timedelta(days=keep_days)).strftime('%Y-%m-%d')
    except Exception:
        return
    state['predictions'] = {k: v for k, v in state.get('predictions', {}).items() if str(v.get('date') or '') >= cutoff}


def validation_state(sport):
    cfg = CONFIG[sport]
    validation_source = cfg['source'].replace('_hybrid_bayes_', '_empirical_bayes_')
    p = MODELS / f"{validation_source}.validation.json"
    try:
        v = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return False, {}
    ok = bool(
        v.get('eligible_for_value')
        and v.get('leakage_guards') == 'PASS'
        and v.get('model_source') == validation_source
    )
    return ok, v


def set_provider(doc, sport, status, rows, labeled_runners, labeled_races, validated=False, validation=None):
    cfg = CONFIG[sport]
    providers = doc.setdefault('providers', [])
    providers[:] = [x for x in providers if x.get('provider') != cfg['provider']]
    providers.append({
        'provider': cfg['provider'],
        'status': status,
        'rows': rows,
        'model_source': cfg['source'],
        'model_validated': bool(validated),
        'model_state': 'VALIDATED_OWN_WALK_FORWARD' if validated else 'PROVISIONAL_HYBRID_UNVALIDATED',
        'value_enabled': bool(validated),
        'history_labeled_runners': labeled_runners,
        'history_labeled_races': labeled_races,
        'own_history_weight': round(min(1.0, labeled_races / cfg['full_own_races']), 4),
        'official_seed_policy': 'USE_OFFICIAL_AI_AS_PRIOR_UNTIL_OWN_HISTORY_MATURES',
        'official_ai_preserved': True,
        'cold_start_policy': f"NO_OWN_PREDICTION_WITHOUT_OFFICIAL_SEED_BEFORE_{cfg['min_own_races_without_seed']}_LABELED_RACES",
        'backfill_source': str(BACKFILL / sport.lower()),
        'pre_race_prediction_state': str(STATE),
        'validation': validation or {},
        'updated_at': datetime.now(KST).isoformat(timespec='seconds'),
    })


def apply_sport(doc, sport, state):
    cfg = CONFIG[sport]
    docs = history_docs(doc.get('date'))
    entity, lane, base, labeled_runners, labeled_races = build_stats(docs, sport)
    updated = 0
    events = 0
    carried = 0
    validation_ok, validation = validation_state(sport)
    fully_own = labeled_races >= cfg['full_own_races']
    validated = bool(validation_ok and fully_own)
    for e in doc.get('events') or []:
        if e.get('sport') != sport:
            continue
        events += 1
        outcomes = e.get('outcomes') or []
        status = e.get('status')
        if status == 'SCHEDULED':
            probs, history_weight, seeded = score_race(e, entity, lane, base, labeled_races, cfg)
            if len(probs) != len(outcomes) or not probs:
                continue
            for o, p in zip(outcomes, probs):
                if o.get('model_source') == cfg['official_source'] and o.get('model_p') is not None:
                    o['official_ai_p'] = o.get('model_p')
                    o['official_ai_source'] = cfg['official_source']
                o['model_p'] = round(float(p), 8)
                o['model_source'] = cfg['source']
                o['model_updated_at'] = now_text()
                o['model_state'] = 'VALIDATED_OWN_WALK_FORWARD' if validated else 'PROVISIONAL_HYBRID_UNVALIDATED'
                o['model_validated'] = bool(validated)
                o['own_history_weight'] = round(history_weight, 4)
                o['official_seed_used'] = bool(seeded)
                save_prediction(state, doc, sport, e, o)
                updated += 1
            e['model_source'] = cfg['source']
            e['model_state'] = 'VALIDATED_OWN_WALK_FORWARD' if validated else 'PROVISIONAL_HYBRID_UNVALIDATED'
            e['model_validated'] = bool(validated)
            e['value_enabled'] = bool(validated)
            e['own_history_weight'] = round(history_weight, 4)
            e['official_seed_used'] = bool(seeded)
        else:
            local_carried = 0
            for o in outcomes:
                old = state.get('predictions', {}).get(state_key(e, o))
                if not old or old.get('model_source') != cfg['source']:
                    continue
                for k in ('model_p', 'model_source', 'model_updated_at', 'model_state', 'model_validated', 'official_ai_p', 'official_ai_source', 'own_history_weight', 'official_seed_used'):
                    if old.get(k) is not None:
                        o[k] = old[k]
                local_carried += 1
                carried += 1

            # A scratch / field change after the pre-race prediction can make
            # the persisted distribution cover only part of the current field.
            # Never publish a partial probability distribution. Results must
            # still be publishable, so fail closed on model fields only.
            active_rows = [o for o in outcomes if o.get('model_p') is not None]
            partial_active = bool(active_rows) and len(active_rows) != len(outcomes)
            if (local_carried and local_carried != len(outcomes)) or partial_active:
                # Results are more important than a stale/incomplete probability
                # distribution. Clear *all active model probability fields*
                # regardless of source so one scratched/new runner cannot block
                # the whole snapshot from publishing.
                for o in outcomes:
                    for k in ('model_p', 'model_source', 'model_updated_at', 'model_state', 'model_validated', 'own_history_weight', 'official_seed_used'):
                        o.pop(k, None)
                e.pop('model_source', None)
                e.pop('model_state', None)
                e.pop('model_validated', None)
                e['model_incomplete'] = True
                e['model_incomplete_reason'] = f"POST_START_PARTIAL_MODEL_{len(active_rows)}_OF_{len(outcomes)}"
                e['value_enabled'] = False
            elif local_carried:
                e['model_source'] = cfg['source']
                e['model_state'] = 'VALIDATED_OWN_WALK_FORWARD' if validated else 'PROVISIONAL_HYBRID_UNVALIDATED'
                e['model_validated'] = bool(validated)
                e['value_enabled'] = bool(validated)
    status = ('PASS' if validated else 'PROVISIONAL') if events else 'NO_TODAY_CARD'
    set_provider(doc, sport, status, updated, labeled_runners, labeled_races, validated, validation)
    return updated, events, labeled_runners, labeled_races, carried


def self_test():
    for sport, n in [('CYCLE', 7), ('BOAT', 6)]:
        raw = normalize([float(i) for i in range(1, n + 1)])
        doc = {'date': '2099-01-01','events': [{'id': f'{sport}-TEST-1','sport': sport,'status': 'SCHEDULED','outcomes': [{'key': f'N{i}', 'number': i, 'name': f'{i} 선수{i}', 'model_p': raw[i - 1], 'model_source': CONFIG[sport]['official_source']} for i in range(1, n + 1)]}],'providers': []}
        state = {'version': 2, 'predictions': {}}
        updated, events, _, _, _ = apply_sport(doc, sport, state)
        vals = [o['model_p'] for o in doc['events'][0]['outcomes']]
        assert events == 1 and updated == n and abs(sum(vals) - 1.0) < 1e-6 and all(0.0 <= x <= 1.0 for x in vals)
        assert all(o.get('official_ai_p') is not None for o in doc['events'][0]['outcomes']) and len(state['predictions']) == n
        doc['events'][0]['status'] = 'FINAL'
        for o in doc['events'][0]['outcomes']:
            o.pop('model_p', None);o.pop('model_source', None)
        _, _, _, _, carried = apply_sport(doc, sport, state)
        assert carried == n and all(o.get('model_source') == CONFIG[sport]['source'] for o in doc['events'][0]['outcomes'])

        # A post-start scratch/field change may leave only a partial saved
        # distribution. Suppress that model rather than blocking results.
        partial = {
            'date': '2099-01-01',
            'events': [{
                'id': f'{sport}-TEST-PARTIAL',
                'sport': sport,
                'status': 'RESULT_PENDING',
                'outcomes': [{'key': f'N{i}', 'number': i, 'name': f'{i} 선수{i}'} for i in range(1, n + 1)],
            }],
            'providers': [],
        }
        partial_state = {'version': 2, 'predictions': {}}
        for i in range(1, n):
            key = f'{sport}-TEST-PARTIAL|N{i}'
            partial_state['predictions'][key] = {
                'date': '2099-01-01',
                'sport': sport,
                'model_p': 1.0 / n,
                'model_source': CONFIG[sport]['source'],
                'model_updated_at': '2099-01-01 00:00:00',
                'model_state': 'PROVISIONAL_HYBRID_UNVALIDATED',
                'model_validated': False,
            }
        # Simulate the exact production failure: the unmatched current runner
        # can still carry an official AI probability.
        partial['events'][0]['outcomes'][-1]['model_p'] = 0.2
        partial['events'][0]['outcomes'][-1]['model_source'] = CONFIG[sport]['official_source']
        apply_sport(partial, sport, partial_state)
        pe = partial['events'][0]
        assert pe.get('model_incomplete') is True
        assert pe.get('value_enabled') is False
        assert all(o.get('model_p') is None for o in pe['outcomes'])

        # Cold-start with no official seed must NOT fabricate uniform own probabilities.
        cold = {'outcomes': [{'key': f'N{i}', 'number': i, 'name': f'{i} 선수{i}'} for i in range(1, n + 1)]}
        entity = defaultdict(lambda: [0, 0]);lane = defaultdict(lambda: [0, 0])
        probs, weight, seeded = score_race(cold, entity, lane, 1.0 / n, 0, CONFIG[sport])
        assert probs == [] and weight == 0.0 and seeded is False
    print('CYCLE_BOAT_OWN_MODEL_SELF_TEST=PASS')


def main():
    if '--self-test' in sys.argv:
        self_test();return
    doc = json.loads(DATA.read_text(encoding='utf-8'))
    state = load_state();state['version'] = 2
    for sport in ('CYCLE', 'BOAT'):
        updated, events, labeled_runners, labeled_races, carried = apply_sport(doc, sport, state)
        print(f'{sport}_OWN_MODEL={"PROVISIONAL" if events else "NO_TODAY_CARD"}')
        print(f'{sport}_OWN_MODEL_ROWS={updated}')
        print(f'{sport}_OWN_MODEL_CARRIED={carried}')
        print(f'{sport}_HISTORY_LABELED_RUNNERS={labeled_runners}')
        print(f'{sport}_HISTORY_LABELED_RACES={labeled_races}')
        print(f'{sport}_OWN_HISTORY_WEIGHT={min(1.0, labeled_races / CONFIG[sport]["full_own_races"]):.4f}')
        print(f'{sport}_VALUE_ENABLED=FALSE')
    trim_state(state, str(doc.get('date') or ''))
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    DATA.write_text(json.dumps(doc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


if __name__ == '__main__':
    main()
