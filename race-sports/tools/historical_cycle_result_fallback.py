import re
import sys
import urllib.error
from datetime import date


def _is_404(exc):
    return isinstance(exc, urllib.error.HTTPError) and int(getattr(exc, 'code', 0)) == 404


def result_url(year, meeting, day, selector=None):
    root = 'https://www.kcycle.or.kr/race/result/general'
    base = f'{root}/{year}/{meeting}/{day}'
    return base if selector is None else f'{base}/{int(selector):02d}'


def _meeting_header(hb, raw):
    try:
        _, text = hb.parse_html(raw)
    except Exception:
        return None
    # Summary header: 2026년 39회 1일차 (10월 02일) 경주결과
    m = re.search(r'(\d{4})년\s*(\d+)회(?:차)?\s*(\d+)일차\s*\((\d{2})월\s*(\d{2})일\)', text)
    if m:
        return {
            'year': int(m.group(1)), 'meeting': int(m.group(2)), 'day': int(m.group(3)),
            'date': f'{int(m.group(1)):04d}-{int(m.group(4)):02d}-{int(m.group(5)):02d}',
        }
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


def _norm(v):
    return re.sub(r'\s+', '', str(v or ''))


def _parse_detail(hb, raw):
    p, text = hb.parse_html(raw)
    heads = list(re.finditer(
        r'(광명|창원|부산)\s*0?(\d{1,2})경주\s*\(([^)]*?)(\d{1,2}:\d{2})\)',
        text
    ))
    if not heads:
        return None
    # The result page contains the race list first and the selected detailed
    # race at the bottom. The last full "(grade time)" heading is the detail.
    h = heads[-1]
    venue = h.group(1)
    race_no = int(h.group(2))
    start_time = h.group(4)

    dm = re.search(
        r'(\d{4})년\s*(\d{2})월\s*(\d{2})일\s*(\d+)회(?:차)?\s*(\d+)일차',
        text[h.start():]
    )
    event_date = None
    local_meeting = None
    local_day = None
    if dm:
        event_date = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        local_meeting = int(dm.group(4))
        local_day = int(dm.group(5))

    rows = []
    for row in p.rows:
        if len(row) < 2:
            continue
        first = re.sub(r'\s+', ' ', str(row[0] or '')).strip()
        m = re.fullmatch(r'([1-7])\s+([가-힣](?:\s*[가-힣]){1,4})', first)
        if not m:
            continue
        rank = hb.as_int(row[1])
        if rank is None or not 1 <= int(rank) <= 7:
            continue
        rows.append({
            'number': int(m.group(1)),
            'name': _norm(m.group(2)),
            'final_rank': int(rank),
        })

    by_num = {}
    for x in rows:
        by_num.setdefault(x['number'], x)
    rows = sorted(by_num.values(), key=lambda x: x['number'])
    if len(rows) < 5:
        return None
    if len({x['final_rank'] for x in rows}) != len(rows):
        return None
    if sum(1 for x in rows if x['final_rank'] == 1) != 1:
        return None

    return {
        'venue': venue,
        'race_no': race_no,
        'start_time': start_time,
        'event_date': event_date,
        'local_meeting': local_meeting,
        'local_day': local_day,
        'runners': rows,
    }


def _summary_matches_detail(summary, detail):
    if not summary or not detail:
        return False
    by_rank = {int(x['final_rank']): x for x in detail['runners']}
    for x in summary.get('top3') or []:
        try:
            rank = int(x.get('rank'))
            number = int(x.get('number'))
        except Exception:
            return False
        d = by_rank.get(rank)
        if not d or int(d['number']) != number or _norm(d['name']) != _norm(x.get('name')):
            return False
    return len(summary.get('top3') or []) == 3


def _ensure_meeting_cursor(hb, state, budget, stats, room):
    cp = state['checkpoints']['cycle']
    if cp.get('cursor_mode') == 'RESULT_DETAIL_MEETING_V2' and cp.get('year') and cp.get('meeting') and cp.get('day'):
        return True

    # Discover the latest official global meeting/day from the result page.
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
        'cursor_mode': 'RESULT_DETAIL_MEETING_V2',
        'year': h['year'],
        'meeting': h['meeting'],
        'day': h['day'],
        'selector': 1,
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

        # Result summary is the authoritative day index and confirmed payouts.
        summary_raw = None
        summary_url = None
        for u in (result_url(year, meeting, day), result_url(year, meeting, day, 1)):
            if not room(1) or not budget.time_left():
                break
            try:
                raw = hb.fetch(u, budget, 'ksports', timeout=12, retries=2)
            except Exception as exc:
                if not _is_404(exc):
                    stats['errors'].append(f'CYCLE {year}-M{meeting}-D{day} RESULT {type(exc).__name__}:{exc}'[:220])
                continue
            mh = _meeting_header(hb, raw)
            if not mh:
                continue
            if mh['year'] == year and mh['meeting'] == meeting and mh['day'] == day:
                summary_raw = raw
                summary_url = u
                break

        if summary_raw is None:
            _step(cp, hb)
            cp['selector'] = 1
            stats['cycle_dates'] += 1
            hb.save_state(state)
            continue

        mh = _meeting_header(hb, summary_raw)
        try:
            event_day = date.fromisoformat(mh['date'])
        except Exception:
            event_day = hb.selected_date(summary_raw, year)

        summary = hb.parse_cycle_results(summary_raw)
        if not summary or event_day is None:
            _step(cp, hb)
            cp['selector'] = 1
            stats['cycle_dates'] += 1
            hb.save_state(state)
            continue

        # KCYCLE result detail already contains all starters + final ranks.
        # Scan selectors and dedupe by venue/race. No historical card request.
        selector = max(1, int(cp.get('selector', 1) or 1))
        unique_details = {}
        empty_or_dup = 0
        max_selector = 32
        while selector <= max_selector and room(1) and budget.time_left():
            u = result_url(year, meeting, day, selector)
            try:
                raw = hb.fetch(u, budget, 'ksports', timeout=10, retries=1)
            except Exception as exc:
                if not _is_404(exc):
                    stats['errors'].append(f'CYCLE {year}-M{meeting}-D{day}-S{selector:02d} DETAIL {type(exc).__name__}:{exc}'[:220])
                selector += 1
                cp['selector'] = selector
                hb.save_state(state)
                continue

            detail = _parse_detail(hb, raw)
            if not detail:
                empty_or_dup += 1
            else:
                key = (detail['venue'], int(detail['race_no']))
                if key in unique_details:
                    empty_or_dup += 1
                else:
                    unique_details[key] = (detail, u)
                    empty_or_dup = 0

            selector += 1
            cp['selector'] = selector
            hb.save_state(state)

            # Stop once all summarized races were recovered, or after enough
            # consecutive selectors add nothing.
            if len(unique_details) >= len(summary):
                break
            if selector > 12 and empty_or_dup >= 8:
                break

        added = 0
        for key, pair in unique_details.items():
            detail, detail_url = pair
            r = summary.get(key)
            if not _summary_matches_detail(r, detail):
                stats['errors'].append(
                    f'CYCLE {event_day} {key[0]}-{key[1]:02d} DETAIL_SUMMARY_MISMATCH'
                )
                continue
            eid = f'CYCLE-{event_day.strftime("%Y%m%d")}-{key[0]}-{key[1]:02d}'
            if eid in seen:
                continue

            outs = [
                {
                    'key': f'N{x["number"]}',
                    'number': x['number'],
                    'name': f'{x["number"]} {x["name"]}',
                    'rider_name': x['name'],
                    'final_rank': x['final_rank'],
                    'won': x['final_rank'] == 1,
                }
                for x in detail['runners']
            ]
            event = {
                'id': eid,
                'sport': 'CYCLE',
                'provider': 'KCYCLE',
                'competition': key[0] + ' 경륜',
                'event_date': event_day.isoformat(),
                'start_time': detail.get('start_time'),
                'race_no': key[1],
                'status': 'FINAL',
                'market_type': 'RUNNERS',
                'outcomes': outs,
                'result': {
                    'official': True,
                    'status': 'CONFIRMED',
                    'top3': r['top3'],
                    'markets': r.get('markets') or [],
                    'source': 'KCYCLE_RESULT_DETAIL_OFFICIAL',
                },
                'source_url': detail_url,
                'summary_source_url': summary_url,
                'meeting': meeting,
                'meeting_day': day,
                'local_meeting': detail.get('local_meeting'),
                'local_day': detail.get('local_day'),
                'feature_contract': {
                    'allowed_prerace_fields': ['rider_name', 'lane_number'],
                    'blocked_postrace_fields': ['final_rank', 'won', 'result', 'markets', 'odds'],
                    'source_note': 'starter identity/lane recovered from official confirmed result detail; outcome labels stored separately',
                },
            }
            hb.append_record('cycle', event)
            seen.add(eid)
            stats['cycle_records'] += 1
            added += 1

        stats['cycle_dates'] += 1
        stats['errors'].append(
            f'CYCLE {event_day} RESULT_DETAIL_SCAN summary={len(summary)} detail={len(unique_details)} added={added}'
        )
        _step(cp, hb)
        cp['selector'] = 1
        hb.save_state(state)


def install(hb):
    hb.backfill_cycle = lambda state, budget, seen, stats, call_limit=None: _backfill_cycle(
        hb, state, budget, seen, stats, call_limit
    )
    return hb


def self_test():
    class Dummy:
        START = {'cycle': date(2011, 1, 1)}
    cp = {'year': 2026, 'meeting': 39, 'day': 1}
    _step(cp, Dummy)
    assert cp == {'year': 2026, 'meeting': 38, 'day': 3}
    cp = {'year': 2026, 'meeting': 1, 'day': 1}
    _step(cp, Dummy)
    assert cp['year'] == 2025 and cp['meeting'] == 60 and cp['day'] == 3

    fixture = '''
    <h2>광명 16경주 (특선 18:56)</h2>
    <div>2026년 10월 02일 39회 1일차</div>
    <table>
      <tr><th>선수명</th><th>순위</th><th>착차</th></tr>
      <tr><td>1 김범수</td><td>4</td><td>1W</td></tr>
      <tr><td>2 류재민</td><td>6</td><td>3/4B</td></tr>
      <tr><td>3 김희준</td><td>3</td><td>1B</td></tr>
      <tr><td>4 공태민</td><td>1</td><td>-</td></tr>
      <tr><td>5 이인우</td><td>5</td><td>1.3/4B</td></tr>
      <tr><td>6 양승원</td><td>2</td><td>1/2B</td></tr>
      <tr><td>7 곽현명</td><td>7</td><td>1.1/4B</td></tr>
    </table>
    '''
    import historical_backfill as hb
    d = _parse_detail(hb, fixture)
    assert d and d['venue'] == '광명' and d['race_no'] == 16 and len(d['runners']) == 7
    assert next(x for x in d['runners'] if x['number'] == 4)['final_rank'] == 1
    print('KCYCLE_RESULT_DETAIL_BACKFILL_SELF_TEST=PASS')


if __name__ == '__main__' and '--self-test' in sys.argv:
    self_test()
