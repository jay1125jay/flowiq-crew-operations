"""No-race fast guard for the preserved KCYCLE official enricher."""
from __future__ import annotations

import json
import sys
from datetime import date

import kcycle_official_enricher_core as core


# Re-export parser helpers for callers/tests that import this module.
for _name in dir(core):
    if not _name.startswith('__') and _name not in globals():
        globals()[_name] = getattr(core, _name)


def _no_race_weekday(payload):
    try:
        d = date.fromisoformat(str(payload.get('date')))
        return d.weekday() not in (4, 5, 6)  # KCYCLE Fri/Sat/Sun
    except Exception:
        return False


def _fast_no_race(payload):
    status = 'NO_RACE_WEEKDAY'
    detail = {'reason': 'NO_CYCLE_EVENT_AND_NON_RACE_WEEKDAY', 'network_calls': 0}
    core.set_provider(payload, 'CYCLE_RESULT_KCYCLE', status, {**detail, 'confirmed': 0})
    core.set_provider(payload, 'CYCLE_AI_KCYCLE', status, {**detail, 'linked': 0, 'meaning': 'official AI rider win probability'})
    core.set_provider(payload, 'CYCLE_LIVE_ODDS_KCYCLE', status, {**detail, 'captured': 0})
    core.DATA.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({
        'KCYCLE_ENRICH': 'PASS',
        'results': status,
        'ai': status,
        'odds': status,
        'network_calls': 0,
    }, ensure_ascii=False))


def main():
    if '--self-test' in sys.argv:
        core.self_test()
        return

    payload = json.loads(core.DATA.read_text(encoding='utf-8'))
    events = [e for e in payload.get('events', []) if e.get('sport') == 'CYCLE']
    if not events and _no_race_weekday(payload):
        _fast_no_race(payload)
        return

    core.main()


if __name__ == '__main__':
    main()
