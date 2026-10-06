"""Fast policy wrapper around the preserved RACEIQ racing collector.

The core parser remains byte-for-byte preserved in racing_static_collector_core.py.
This wrapper only prevents known no-race weekdays and official-site outages from
consuming the whole GitHub Actions refresh window.
"""
from __future__ import annotations

import racing_static_collector_core as core


# KBOAT's 2026 operating calendar uses Wednesday/Thursday race days. On other
# weekdays there is no card to probe, so return an explicit normal state without
# hitting three slow card endpoints.
KBOAT_RACE_WEEKDAYS = {2, 3}  # datetime.weekday(): Wed, Thu
_core_kboat_fetch = core.kboat_fetch
_core_collect_boat = core.collect_boat


def _bounded_kboat_fetch(url, timeout=15, retries=3):
    # A dead official endpoint must not stall the entire four-sport refresh.
    # Race-day calls still use the same official URLs/parsers, just bounded.
    return _core_kboat_fetch(url, timeout=min(int(timeout), 8), retries=1)


def _collect_boat(z, errors):
    if z.weekday() not in KBOAT_RACE_WEEKDAYS:
        return [], [
            {
                'provider': 'BOAT_KBOAT',
                'status': 'NO_RACE_WEEKDAY',
                'detail': {'published': 0, 'schedule_policy': 'KBOAT_2026_WED_THU'},
            },
            {
                'provider': 'BOAT_RESULT_KBOAT',
                'status': 'NO_TODAY_CARD',
                'detail': {'confirmed': 0},
            },
            {
                'provider': 'BOAT_ODDS_KBOAT',
                'status': 'NO_TODAY_CARD',
                'detail': {
                    'market': '단승식',
                    'window': '경기 120분 전~35분 후',
                    'odds_events': 0,
                    'source': 'KBOAT_FINAL',
                },
            },
        ]

    events, providers = _core_collect_boat(z, errors)
    if not events:
        for p in providers:
            if p.get('provider') in {'BOAT_RESULT_KBOAT', 'BOAT_ODDS_KBOAT'}:
                p['status'] = 'NO_TODAY_CARD'
    return events, providers


core.kboat_fetch = _bounded_kboat_fetch
core.collect_boat = _collect_boat

# Re-export helpers so existing imports keep working.
for _name in dir(core):
    if not _name.startswith('__') and _name not in globals():
        globals()[_name] = getattr(core, _name)


if __name__ == '__main__':
    core.main()
