#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'data' / 'sports_today.json'


def normalize_multibook(payload: dict) -> str:
    providers = payload.get('providers') or []
    row = next((p for p in providers if p.get('provider') == 'SPORTS_ODDS_MULTIBOOK'), None)
    if not isinstance(row, dict):
        return 'ABSENT'

    errors = row.get('errors') or []
    meta = row.get('meta') or []
    enriched = int(row.get('events_enriched') or 0)
    queried = [m for m in meta if m.get('status') == 'PASS']

    if errors:
        status = 'PARTIAL'
    elif not queried:
        status = 'NO_ELIGIBLE_LEAGUE'
    elif enriched <= 0:
        status = 'NO_MATCH'
    else:
        status = 'PASS'

    row['status'] = status
    row['status_contract'] = 'PASS_ONLY_WHEN_AT_LEAST_ONE_EVENT_ENRICHED; NO_ELIGIBLE_LEAGUE_AND_NO_MATCH_ARE_NON_ERROR_STATES'

    odds_provider = payload.get('odds_provider')
    if isinstance(odds_provider, dict) and odds_provider.get('provider') == 'SportsGameOdds':
        odds_provider['status'] = status
        odds_provider['status_contract'] = row['status_contract']

    return status


def finalize(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding='utf-8'))
    status = normalize_multibook(payload)
    integrity = payload.setdefault('integrity', {})
    integrity['stale_events'] = sum(
        1 for e in payload.get('events', [])
        if e.get('stale') or e.get('data_state') == 'STALE_LAST_KNOWN_GOOD'
    )
    integrity['sports_multibook_status'] = status
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    result = {
        'SPORTS_SNAPSHOT_FINALIZE': 'PASS',
        'multibook_status': status,
        'events': len(payload.get('events', [])),
        'stale_events': integrity['stale_events'],
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def self_test():
    cases = [
        ({'providers':[{'provider':'SPORTS_ODDS_MULTIBOOK','meta':[{'status':'SKIP'}],'errors':[],'events_enriched':0}]}, 'NO_ELIGIBLE_LEAGUE'),
        ({'providers':[{'provider':'SPORTS_ODDS_MULTIBOOK','meta':[{'status':'PASS'}],'errors':[],'events_enriched':0}]}, 'NO_MATCH'),
        ({'providers':[{'provider':'SPORTS_ODDS_MULTIBOOK','meta':[{'status':'PASS'}],'errors':[],'events_enriched':1}]}, 'PASS'),
        ({'providers':[{'provider':'SPORTS_ODDS_MULTIBOOK','meta':[{'status':'PASS'}],'errors':[{'x':1}],'events_enriched':0}]}, 'PARTIAL'),
    ]
    for payload, expected in cases:
        got = normalize_multibook(payload)
        assert got == expected, (got, expected)
    print('SPORTS_SNAPSHOT_FINALIZE_SELF_TEST=PASS')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path', nargs='?', default=str(DEFAULT))
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    finalize(Path(a.path))


if __name__ == '__main__':
    main()
