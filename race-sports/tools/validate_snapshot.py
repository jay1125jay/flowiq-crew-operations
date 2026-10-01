import json
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
    bad_bull = []
    for e in events:
        if e.get('sport') == 'BULL':
            keys = [o.get('key') for o in e.get('outcomes', [])]
            if keys and keys != ['RED', 'DRAW', 'BLUE']:
                bad_bull.append(e.get('id'))
        for o in e.get('outcomes', []):
            if o.get('odds') is not None:
                try:
                    if float(o['odds']) <= 0:
                        bad_odds.append((e.get('id'), o.get('key')))
                except Exception:
                    bad_odds.append((e.get('id'), o.get('key')))

    if bad_odds:
        fail('NON_POSITIVE_ODDS')
    if bad_bull:
        fail('BULL_OUTCOME_ORDER')

    # A recovered stale feed is allowed; silently losing same-day events is not.
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
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
