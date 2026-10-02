import sys
import urllib.error
from datetime import date


def _is_404(exc):
    return isinstance(exc, urllib.error.HTTPError) and int(getattr(exc, 'code', 0)) == 404


def result_candidates(year, week, day):
    root = 'https://www.kcycle.or.kr/race/result/general'
    return [
        f'{root}/{year}/{week}/{day}',
        f'{root}/{year}/{week}/{day}/01',
        root,
    ]


def _advance(hb, state, stats):
    stats['cycle_dates'] += 1
    hb.advance_day(state['checkpoints'], 'cycle', hb.START['cycle'])
    hb.save_state(state)


def _backfill_cycle(hb, state, budget, seen, stats, call_limit=None):
    cp = state['checkpoints']['cycle']
    start_calls = int(budget.ledger.get('ksports', 0))

    def room(n=1):
        used = int(budget.ledger.get('ksports', 0)) - start_calls
        return (call_limit is None or used + n <= call_limit) and budget.available('ksports') >= n

    while not cp.get('complete') and room(1) and budget.time_left():
        d = date.fromisoformat(cp['cursor_date'])
        if d < hb.START['cycle']:
            cp['complete'] = True
            hb.save_state(state)
            break
        if d.weekday() not in (4, 5, 6):
            _advance(hb, state, stats)
            continue

        iso = d.isocalendar()
        day = {4: 1, 5: 2, 6: 3}[d.weekday()]

        # KCYCLE meeting number is not the ISO week number. Probe a bounded
        # range around the calendar week and accept only a card whose visible
        # official date exactly matches the requested historical date.
        card_raw = None
        card_url = None
        meeting = None
        candidates = []
        for delta in (0, -1, -2, -3, -4, -5, -6, 1, 2):
            m = int(iso.week) + delta
            if m < 1 or m > 60 or m in candidates:
                continue
            candidates.append(m)

        future_seen = False
        jump_date = None
        for m in candidates:
            if not room(1) or not budget.time_left():
                break
            url = hb.CYCLE_CARD.format(year=d.year, week=m, day=day)
            try:
                raw = hb.fetch(url, budget, 'ksports', timeout=10, retries=1)
            except Exception as exc:
                if _is_404(exc):
                    continue
                stats['errors'].append(f'CYCLE {d} CARD M{m} {type(exc).__name__}:{exc}'[:220])
                continue
            visible = hb.selected_date(raw, d.year)
            if visible == d:
                card_raw = raw
                card_url = url
                meeting = m
                break
            if visible is not None:
                if visible > d:
                    future_seen = True
                elif visible < d and future_seen:
                    # Requested date is bracketed between two official meetings.
                    # Jump directly to the previous real meeting day instead of
                    # burning one workflow run per empty calendar day.
                    jump_date = visible
                    break

        if card_raw is None:
            if jump_date is not None:
                cp['cursor_date'] = jump_date.isoformat()
                stats['cycle_dates'] += 1
                hb.save_state(state)
                stats['errors'].append(f'CYCLE {d} NON_MEETING_JUMP:{jump_date}'[:220])
                continue
            stats['errors'].append(f'CYCLE {d} CARD_MEETING_NOT_RESOLVED:{candidates}'[:220])
            _advance(hb, state, stats)
            continue

        card = hb.parse_cycle_card(card_raw, d)
        if not card:
            stats['errors'].append(f'CYCLE {d} CARD_EMPTY_SKIPPED'[:220])
            _advance(hb, state, stats)
            continue

        results = None
        selected_result_url = None
        attempts = []
        for result_url in result_candidates(d.year, meeting, day):
            if not room(1) or not budget.time_left():
                break
            try:
                result_raw = hb.fetch(result_url, budget, 'ksports', timeout=10, retries=1)
            except Exception as exc:
                if _is_404(exc):
                    attempts.append('404:' + result_url)
                    continue
                stats['errors'].append(f'CYCLE {d} RESULT {type(exc).__name__}:{exc}'[:220])
                results = None
                selected_result_url = None
                break

            result_day = hb.selected_date(result_raw, d.year)
            # The generic endpoint always renders some meeting. It is accepted
            # only when its visible date is exactly the requested historical day.
            if result_url.endswith('/general'):
                if result_day != d:
                    attempts.append(f'DATE_MISMATCH:{result_day}:{result_url}')
                    continue
            elif result_day is not None and result_day != d:
                attempts.append(f'DATE_MISMATCH:{result_day}:{result_url}')
                continue

            parsed = hb.parse_cycle_results(result_raw)
            if parsed:
                results = parsed
                selected_result_url = result_url
                break
            attempts.append('EMPTY:' + result_url)

        if not results:
            if attempts:
                stats['errors'].append(f'CYCLE {d} RESULT_FALLBACK_MISS:' + '|'.join(attempts)[:150])
            _advance(hb, state, stats)
            continue

        for key, meta in card.items():
            result = results.get(key)
            if not result:
                continue
            venue, race_no = key
            event_id = f'CYCLE-{d.strftime("%Y%m%d")}-{venue}-{race_no:02d}'
            if event_id in seen:
                continue
            top_by = {x['number']: x['rank'] for x in result['top3']}
            outcomes = [
                {
                    'key': f'N{n}', 'number': n, 'name': f'{n} {name}',
                    'rider_name': name, 'final_rank': top_by.get(n),
                    'won': top_by.get(n) == 1,
                }
                for n, name in sorted(meta['runners'].items())
            ]
            # Keep complete-field histories only. Missing top-3 riders indicate
            # card/result mismatch and must never enter model history.
            if len(outcomes) < 5 or sum(1 for o in outcomes if o['won']) != 1:
                continue
            if not all(any(o['number'] == x['number'] for o in outcomes) for x in result['top3']):
                continue
            event = {
                'id': event_id, 'sport': 'CYCLE', 'provider': 'KCYCLE',
                'competition': venue + ' 경륜', 'event_date': d.isoformat(),
                'start_time': meta['start_time'], 'race_no': race_no,
                'status': 'FINAL', 'market_type': 'RUNNERS', 'outcomes': outcomes,
                'result': {
                    'official': True, 'status': 'CONFIRMED',
                    'top3': result['top3'], 'markets': result['markets'],
                    'source': 'KCYCLE_RESULT_OFFICIAL',
                },
                'source_url': selected_result_url,
                'card_source_url': card_url,
                'meeting': meeting,
            }
            hb.append_record('cycle', event)
            seen.add(event_id)
            stats['cycle_records'] += 1

        _advance(hb, state, stats)


def install(hb):
    hb.backfill_cycle = lambda state, budget, seen, stats, call_limit=None: _backfill_cycle(
        hb, state, budget, seen, stats, call_limit
    )
    return hb


def self_test():
    urls = result_candidates(2026, 38, 3)
    assert urls[0].endswith('/2026/38/3')
    assert urls[1].endswith('/2026/38/3/01')
    assert urls[2].endswith('/race/result/general')
    assert len(set(urls)) == 3
    print('KCYCLE_HISTORICAL_RESULT_FALLBACK_SELF_TEST=PASS')


if __name__ == '__main__' and '--self-test' in sys.argv:
    self_test()
