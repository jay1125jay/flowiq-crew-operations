"""Fast policy wrapper around the preserved RACEIQ racing collector.

The core parser remains in racing_static_collector_core.py. This wrapper adds
strict operating-calendar policy and bounded network calls around the official
sources.
"""
from __future__ import annotations

import racing_static_collector_core as core


# KBOAT 2026 regular race operation: Wednesday = meeting day 1,
# Thursday = meeting day 2. Never infer the meeting day from the web page's
# currently-selected option because the official site can expose the adjacent
# day's selection while both cards are already published.
KBOAT_DAY_BY_WEEKDAY = {2: 1, 3: 2}  # datetime.weekday(): Wed=1, Thu=2
KBOAT_RACE_WEEKDAYS = set(KBOAT_DAY_BY_WEEKDAY)
_core_kboat_fetch = core.kboat_fetch
_core_collect_boat = core.collect_boat
_core_selected_date = core.selected_date
_active_boat_date = None
_expected_boat_day = None
_SKIP_CARD = '__RACEIQ_SKIP_KBOAT_NON_TODAY_DAY__'


def _bounded_kboat_fetch(url, timeout=15, retries=3):
    # During collect_boat, suppress adjacent meeting-day card probes. This lets
    # the existing parser stay intact while forcing the official weekday/day
    # contract. Other result/odds URLs are not suppressed.
    if _expected_boat_day is not None and '/race/card/decision/' in url:
        try:
            requested_day = int(url.rstrip('/').split('/')[-1])
        except Exception:
            requested_day = None
        if requested_day is not None and requested_day != _expected_boat_day:
            return _SKIP_CARD
    return _core_kboat_fetch(url, timeout=min(int(timeout), 8), retries=1)


def _boat_selected_date(raw, y):
    if raw == _SKIP_CARD:
        return '1900-01-01'
    # For the single weekday-authorized card, bind the date to the runtime KST
    # date. The weekday/day contract is checked again on every published event.
    if _active_boat_date is not None:
        return _active_boat_date
    return _core_selected_date(raw, y)


def _collect_boat(z, errors):
    global _active_boat_date, _expected_boat_day
    expected_day = KBOAT_DAY_BY_WEEKDAY.get(z.weekday())
    if expected_day is None:
        return [], [
            {
                'provider': 'BOAT_KBOAT',
                'status': 'NO_RACE_WEEKDAY',
                'detail': {'published': 0, 'schedule_policy': 'KBOAT_2026_WED_DAY1_THU_DAY2'},
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

    _active_boat_date = z.strftime('%Y-%m-%d')
    _expected_boat_day = expected_day
    try:
        events, providers = _core_collect_boat(z, errors)
    finally:
        _active_boat_date = None
        _expected_boat_day = None

    # Fail closed if the core ever returns an adjacent meeting day again.
    bad = []
    expected_token = f'-{expected_day}-'
    expected_comp = f'{expected_day}일차'
    for event in events:
        if expected_token not in str(event.get('id', '')) or expected_comp not in str(event.get('competition', '')):
            bad.append(event.get('id'))
    if bad:
        raise RuntimeError(f'KBOAT_MEETING_DAY_MISMATCH:weekday={z.weekday()}:expected_day={expected_day}:events={bad[:5]}')

    for p in providers:
        if p.get('provider') == 'BOAT_KBOAT':
            detail = p.setdefault('detail', {})
            detail['day'] = expected_day
            detail['schedule_policy'] = 'KBOAT_2026_WED_DAY1_THU_DAY2'
            detail['date_bound'] = z.strftime('%Y-%m-%d')
        if not events and p.get('provider') in {'BOAT_RESULT_KBOAT', 'BOAT_ODDS_KBOAT'}:
            p['status'] = 'NO_TODAY_CARD'
    return events, providers


core.kboat_fetch = _bounded_kboat_fetch
core.selected_date = _boat_selected_date
core.collect_boat = _collect_boat

# Re-export helpers so existing imports keep working.
for _name in dir(core):
    if not _name.startswith('__') and _name not in globals():
        globals()[_name] = getattr(core, _name)


if __name__ == '__main__':
    core.main()
