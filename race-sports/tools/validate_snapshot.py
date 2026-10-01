import json
import math
import sys
from collections import Counter
from pathlib import Path


def fail(msg):
    print('VALIDATION_FAIL=' + msg)
    raise SystemExit(2)


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else 'race-sports/data/today.json')
    try:
        p = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        fail('JSON:' + str(e))

    events = p.get('events') or []
    ids = [e.get('id') for e in events if e.get('id')]
    if len(ids) != len(set(ids)):
        fail('DUPLICATE_EVENT_ID')

    sports = Counter(e.get('sport') for e in events)
    stale = sum(1 for e in events if e.get('stale'))
    bad_odds = []
    bad_model = []
    bad_bull = []
    bad_bull_result = []
    bad_bull_odds = []
    bad_bull_model = []

    for e in events:
        outcomes = e.get('outcomes', [])
        model_values = [o.get('model_p') for o in outcomes]
        populated = [v for v in model_values if v is not None]
        if populated:
            if len(populated) != len(outcomes):
                bad_model.append((e.get('id'), 'PARTIAL_MODEL'))
            else:
                try:
                    vals = [float(v) for v in populated]
                    if not all(math.isfinite(v) and 0.0 <= v <= 1.0 for v in vals):
                        bad_model.append((e.get('id'), 'MODEL_RANGE'))
                    elif abs(sum(vals) - 1.0) > 0.03:
                        bad_model.append((e.get('id'), f'MODEL_SUM:{sum(vals):.6f}'))
                except Exception:
                    bad_model.append((e.get('id'), 'MODEL_PARSE'))

        if e.get('sport') == 'BULL':
            keys = [o.get('key') for o in outcomes]
            if keys and keys != ['RED', 'DRAW', 'BLUE']:
                bad_bull.append(e.get('id'))

            winner = ((e.get('result') or {}).get('winner') or {}).get('key')
            if winner is not None and winner not in ('RED', 'DRAW', 'BLUE'):
                bad_bull_result.append((e.get('id'), winner))

            cpc = [o for o in outcomes if o.get('odds_source') == 'CPC_FINAL_SINGLE_AUTO']
            if cpc:
                cmap = {o.get('key'): o for o in cpc}
                if set(cmap) != {'RED', 'DRAW', 'BLUE'}:
                    bad_bull_odds.append((e.get('id'), 'MISSING_THREE_WAY'))
                else:
                    for key in ('RED', 'DRAW', 'BLUE'):
                        try:
                            if float(cmap[key].get('odds') or 0) <= 0:
                                bad_bull_odds.append((e.get('id'), key))
                        except Exception:
                            bad_bull_odds.append((e.get('id'), key))

            if populated:
                sources = {o.get('model_source') for o in outcomes}
                if sources != {'bull_threeclass_direct_v1.3.0'}:
                    bad_bull_model.append((e.get('id'), sorted(str(x) for x in sources)))

        for o in outcomes:
            if o.get('odds') is not None:
                try:
                    if float(o['odds']) <= 0:
                        bad_odds.append((e.get('id'), o.get('key')))
                except Exception:
                    bad_odds.append((e.get('id'), o.get('key')))

    if bad_odds:
        fail('NON_POSITIVE_ODDS')
    if bad_model:
        fail('MODEL_PROBABILITY:' + str(bad_model[:3]))
    if bad_bull:
        fail('BULL_OUTCOME_ORDER')
    if bad_bull_result:
        fail('BULL_RESULT_KEY')
    if bad_bull_odds:
        fail('BULL_THREE_WAY_ODDS')
    if bad_bull_model:
        fail('BULL_MODEL_SOURCE')

    guard = next((x for x in p.get('providers', []) if x.get('provider') == 'SNAPSHOT_GUARD'), None)
    if stale and not guard:
        fail('STALE_WITHOUT_GUARD')

    print(json.dumps({
        'VALIDATION': 'PASS',
        'date': p.get('date'),
        'events': len(events),
        'by_sport': dict(sports),
        'stale_events': stale,
        'guard': (guard or {}).get('status'),
        'model_probability_guard': True,
        'bull_three_way_guard': True,
        'bull_model_source_guard': True,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
