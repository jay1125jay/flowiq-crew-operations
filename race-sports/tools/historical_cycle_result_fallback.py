import re
import sys
import urllib.error


def _is_404(exc):
    return isinstance(exc, urllib.error.HTTPError) and int(getattr(exc, 'code', 0)) == 404


def result_candidates(year, meeting, day):
    root = 'https://www.kcycle.or.kr/race/result/general'
    return [
        f'{root}/{year}/{meeting}/{day}',
        f'{root}/{year}/{meeting}/{day}/01',
        root,
    ]


def _meeting_header(hb, raw):
    try:
        _, text = hb.parse_html(raw)
    except Exception:
        return None
    pats = [
        r'(\d{4})년\s*(\d+)회(?:차)?\s*(\d+)일차\s*\((\d{2})월\s*(\d{2})일\)',
        r'(\d{4})년\s*(\d+)회(?:차)?\s*(\d+)일차',
    ]
    for pat in pats:
        m = re.search(pat, text)
        if not m:
            continue
        out = {'year': int(m.group(1)), 'meeting': int(m.group(2)), 'day': int(m.group(3))}
        if len(m.groups()) >= 5:
            out['date'] = f'{int(m.group(1)):04d}-{int(m.group(4)):02d}-{int(m.group(5)):02d}'
        return out
    return None


def _step(cp, hb):
    day = int(cp.get('day', 3))
    meeting = int(cp.get('meeting', 1))
    year = int(cp.get('year', 2026))
    if day > 1:
        day -= 1
    else:
        day = 3
        meeting -= 1
        if meeting < 1:
            year -= 1
            meeting = 60
    cp['year'] = year
    cp['meeting'] = meeting
    cp['day'] = day
    if year < hb.START['cycle'].year:
        cp['complete'] = True


def _ensure_meeting_cursor(hb, state, budget, stats, room):
    cp = state['checkpoints']['cycle']
    if cp.get('cursor_mode') == 'MEETING_DAY_V1' and cp.get('year') and cp.get('meeting') and cp.get('day'):
        return True

    # One official request discovers the latest published KCYCLE meeting/day.
    if not room(1) or not budget.time_left():
        return False
    root = 'https://www.kcycle.or.kr/race/result/general'
    try:
        raw = hb.fetch(root, budget, 'ksports', timeout=12, retries=2)
    except Exception as exc:
        stats['errors'].append(f'CYCLE CURSOR_DISCOVERY {type(exc).__name__}:{exc}'[:220])
        return False
    h = _meeting_header(hb, raw)
    if not h:
        stats['errors'].append('CYCLE CURSOR_DISCOVERY_HEADER_MISSING')
        return False
    cp.clear()
    cp.update({
        'cursor_mode': 'MEETING_DAY_V1',
        'year': h['year'],
        'meeting': h['meeting'],
        'day': h['day'],
        'complete': False,
    })
    hb.save_state(state)
    return True


def _backfill_cycle(hb, state, budget, seen, stats, call_limit=None):
    cp = state['checkpoints']['cycle']
    start_calls = int(budget.ledger.get('ksports', 0))

    def room(n=1):
        used = int(budget.ledger.get('ksports', 0)) - start_calls
        return (call_limit is None or used + n <= call_limit) and budget.available('ksports') >= n

    if not _ensure_meeting_cursor(hb, state, budget, stats, room):
        return

    while not cp.get('complete') and room(2) and budget.time_left():
        year = int(cp['year'])
        meeting = int(cp['meeting'])
        day = int(cp['day'])

        if year < hb.START['cycle'].year:
            cp['complete'] = True
            hb.save_state(state)
            break

        card_url = hb.CYCLE_CARD.format(year=year, week=meeting, day=day)
        try:
            card_raw = hb.fetch(card_url, budget, 'ksports', timeout=12, retries=2)
        except Exception as exc:
            if not _is_404(exc):
                stats['errors'].append(f'CYCLE {year}-M{meeting}-D{day} CARD {type(exc).__name__}:{exc}'[:220])
            _step(cp, hb)
            stats['cycle_dates'] += 1
            hb.save_state(state)
            continue

        ch = _meeting_header(hb, card_raw)
        # Invalid meeting/day URLs sometimes render another page. Never accept
        # unless the visible official header matches the requested cursor.
        if ch and (ch['year'] != year or ch['meeting'] != meeting or ch['day'] != day):
            _step(cp, hb)
            stats['cycle_dates'] += 1
            hb.save_state(state)
            continue

        d = hb.selected_date(card_raw, year)
        if d is None and ch and ch.get('date'):
            try:
                from datetime import date
                yy, mm, dd = map(int, ch['date'].split('-'))
                d = date(yy, mm, dd)
            except Exception:
                d = None

        card = hb.parse_cycle_card(card_raw, d)
        if not card or d is None:
            _step(cp, hb)
            stats['cycle_dates'] += 1
            hb.save_state(state)
            continue

        results = None
        selected_result_url = None
        for result_url in result_candidates(year, meeting, day):
            if not room(1) or not budget.time_left():
                break
            try:
                result_raw = hb.fetch(result_url, budget, 'ksports', timeout=12, retries=2)
            except Exception:
                continue
            rh = _meeting_header(hb, result_raw)
            rd = hb.selected_date(result_raw, year)
            if rh and (rh['year'] != year or rh['meeting'] != meeting or rh['day'] != day):
                continue
            if rd is not None and rd != d:
                continue
            parsed = hb.parse_cycle_results(result_raw)
            if parsed:
                results = parsed
                selected_result_url = result_url
                break

        if results:
            for key, meta in card.items():
                result = results.get(key)
                if not result:
                    continue
                venue, race_no = key
                event_id = f'CYCLE-{d.strftime("%Y%m%d")}-{venue}-{race_no:02d}'
                if event_id in seen:
                    continue
                card_names = {int(n): re.sub(r'\s+', '', str(name)) for n, name in meta['runners'].items()}
                identity_ok = True
                for x in result['top3']:
                    try:
                        n = int(x['number'])
                    except Exception:
                        identity_ok = False
                        break
                    if card_names.get(n) != re.sub(r'\s+', '', str(x.get('name') or '')):
                        identity_ok = False
                        break
                if not identity_ok:
                    stats['errors'].append(f'CYCLE {event_id} CARD_RESULT_NAME_MISMATCH')
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
                if len(outcomes) < 5 or sum(1 for o in outcomes if o['won']) != 1:
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
                    'meeting_day': day,
                }
                hb.append_record('cycle', event)
                seen.add(event_id)
                stats['cycle_records'] += 1

        stats['cycle_dates'] += 1
        _step(cp, hb)
        hb.save_state(state)


def install(hb):
    hb.backfill_cycle = lambda state, budget, seen, stats, call_limit=None: _backfill_cycle(
        hb, state, budget, seen, stats, call_limit
    )
    return hb


def self_test():
    class Dummy:
        START = {'cycle': __import__('datetime').date(2011, 1, 1)}
    cp = {'year': 2026, 'meeting': 39, 'day': 1}
    _step(cp, Dummy)
    assert cp == {'year': 2026, 'meeting': 38, 'day': 3}
    cp = {'year': 2026, 'meeting': 1, 'day': 1}
    _step(cp, Dummy)
    assert cp['year'] == 2025 and cp['meeting'] == 60 and cp['day'] == 3
    urls = result_candidates(2026, 38, 3)
    assert urls[0].endswith('/2026/38/3')
    assert urls[1].endswith('/2026/38/3/01')
    assert urls[2].endswith('/race/result/general')
    print('KCYCLE_MEETING_CURSOR_SELF_TEST=PASS')


if __name__ == '__main__' and '--self-test' in sys.argv:
    self_test()
