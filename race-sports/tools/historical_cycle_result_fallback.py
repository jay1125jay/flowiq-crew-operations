import re
import sys
import urllib.error
from datetime import date

MEET_CODES = {'광명': '001', '창원': '002', '부산': '004'}


def _is_404(exc):
    return isinstance(exc, urllib.error.HTTPError) and int(getattr(exc, 'code', 0)) == 404


def summary_url(year, meeting, day):
    return f'https://www.kcycle.or.kr/race/result/general/{int(year)}/{int(meeting):02d}/{int(day)}'


def detail_url(year, meeting, day, venue, race_no):
    return (
        f'https://www.kcycle.or.kr/race/result/general/{int(year)}/{int(meeting):02d}/{int(day)}/'
        f'{MEET_CODES[venue]}/{int(race_no):02d}'
    )


def _meeting_header(hb, raw):
    try:
        _, text = hb.parse_html(raw)
    except Exception:
        return None
    m = re.search(r'(\d{4})년\s*(\d+)회(?:차)?\s*(\d+)일차\s*\((\d{2})월\s*(\d{2})일\)', text)
    if not m:
        return None
    return {
        'year': int(m.group(1)),
        'meeting': int(m.group(2)),
        'day': int(m.group(3)),
        'date': f'{int(m.group(1)):04d}-{int(m.group(4)):02d}-{int(m.group(5)):02d}',
    }


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


def _parse_detail(hb, raw, venue, race_no, event_day):
    p, text = hb.parse_html(raw)

    # Exact detail URL is authoritative for venue/race. Parse the table whose
    # rows are "lane + rider name" followed by final rank.
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

    start_time = None
    q = re.search(
        rf'{re.escape(venue)}\s*0?{int(race_no)}경주\s*\([^)]*?(\d{{1,2}}:\d{{2}})\)',
        text
    )
    if q:
        start_time = q.group(1)

    local_meeting = None
    local_day = None
    # Detail header may show local venue meeting, e.g. "34회 1일차
    # (광명: 39회 1일차)". Keep it as metadata only.
    for pat in (
        r'(\d{4})년\s*(\d{2})월\s*(\d{2})일\s*(\d+)회(?:차)?\s*(\d+)일차',
        r'(\d+)회(?:차)?\s*(\d+)일차\s*\(광명:\s*\d+회\s*\d+일차\)',
    ):
        m = re.search(pat, text)
        if m:
            if len(m.groups()) >= 5:
                local_meeting, local_day = int(m.group(4)), int(m.group(5))
            else:
                local_meeting, local_day = int(m.group(1)), int(m.group(2))
            break

    return {
        'venue': venue,
        'race_no': int(race_no),
        'start_time': start_time,
        'event_date': event_day,
        'local_meeting': local_meeting,
        'local_day': local_day,
        'runners': rows,
    }


def _summary_matches_detail(summary, detail):
    if not summary or not detail:
        return False
    by_rank = {int(x['final_rank']): x for x in detail['runners']}
    top3 = summary.get('top3') or []
    if len(top3) != 3:
        return False
    for x in top3:
        try:
            rank = int(x.get('rank'))
            number = int(x.get('number'))
        except Exception:
            return False
        d = by_rank.get(rank)
        if not d or int(d['number']) != number or _norm(d['name']) != _norm(x.get('name')):
            return False
    return True


def _ensure_meeting_cursor(hb, state, budget, stats, room):
    cp = state['checkpoints']['cycle']
    if cp.get('cursor_mode') == 'DETAIL_ROUTE_V3' and cp.get('year') and cp.get('meeting') and cp.get('day'):
        return True

    # Preserve every prior meeting/day cursor version.
    if cp.get('cursor_mode') in {'MEETING_DAY_V1', 'RESULT_DETAIL_MEETING_V2'} and cp.get('year') and cp.get('meeting') and cp.get('day'):
        cp['cursor_mode'] = 'DETAIL_ROUTE_V3'
        cp.pop('selector', None)
        cp['complete'] = False
        hb.save_state(state)
        return True

    # Fresh state only: discover current official round/day.
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
        'cursor_mode': 'DETAIL_ROUTE_V3',
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

        su = summary_url(year, meeting, day)
        try:
            summary_raw = hb.fetch(su, budget, 'ksports', timeout=12, retries=2)
        except Exception as exc:
            if not _is_404(exc):
                stats['errors'].append(f'CYCLE {year}-M{meeting}-D{day} SUMMARY {type(exc).__name__}:{exc}'[:220])
            _step(cp, hb)
            stats['cycle_dates'] += 1
            hb.save_state(state)
            continue

        mh = _meeting_header(hb, summary_raw)
        if not mh or mh['year'] != year or mh['meeting'] != meeting or mh['day'] != day:
            _step(cp, hb)
            stats['cycle_dates'] += 1
            hb.save_state(state)
            continue

        event_day = date.fromisoformat(mh['date'])
        summary = hb.parse_cycle_results(summary_raw)
        if not summary:
            _step(cp, hb)
            stats['cycle_dates'] += 1
            hb.save_state(state)
            continue

        added = 0
        detail_ok = 0
        detail_fail = 0
        for (venue, race_no), result in sorted(summary.items()):
            if venue not in MEET_CODES or not room(1) or not budget.time_left():
                break
            eid = f'CYCLE-{event_day.strftime("%Y%m%d")}-{venue}-{int(race_no):02d}'
            if eid in seen:
                continue

            du = detail_url(year, meeting, day, venue, race_no)
            try:
                raw = hb.fetch(du, budget, 'ksports', timeout=12, retries=2)
            except Exception as exc:
                detail_fail += 1
                stats['errors'].append(
                    f'CYCLE {eid} DETAIL {type(exc).__name__}:{exc}'[:220]
                )
                continue

            detail = _parse_detail(hb, raw, venue, race_no, event_day)
            if not _summary_matches_detail(result, detail):
                detail_fail += 1
                stats['errors'].append(f'CYCLE {eid} DETAIL_SUMMARY_MISMATCH URL={du}'[:300])
                continue

            detail_ok += 1
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
                'competition': venue + ' 경륜',
                'event_date': event_day.isoformat(),
                'start_time': detail.get('start_time'),
                'race_no': int(race_no),
                'status': 'FINAL',
                'market_type': 'RUNNERS',
                'outcomes': outs,
                'result': {
                    'official': True,
                    'status': 'CONFIRMED',
                    'top3': result['top3'],
                    'markets': result.get('markets') or [],
                    'source': 'KCYCLE_RESULT_DETAIL_OFFICIAL',
                },
                'source_url': du,
                'summary_source_url': su,
                'meeting': meeting,
                'meeting_day': day,
                'local_meeting': detail.get('local_meeting'),
                'local_day': detail.get('local_day'),
                'feature_contract': {
                    'allowed_prerace_fields': ['rider_name', 'lane_number'],
                    'blocked_postrace_fields': ['final_rank', 'won', 'result', 'markets', 'odds'],
                    'source_note': 'starter identity/lane recovered from official confirmed result detail; labels kept separately',
                },
            }
            hb.append_record('cycle', event)
            seen.add(eid)
            stats['cycle_records'] += 1
            added += 1

        stats['cycle_dates'] += 1
        stats['errors'].append(
            f'CYCLE {event_day} DETAIL_ROUTE summary={len(summary)} ok={detail_ok} fail={detail_fail} added={added}'
        )
        _step(cp, hb)
        hb.save_state(state)


def install(hb):
    hb.backfill_cycle = lambda state, budget, seen, stats, call_limit=None: _backfill_cycle(
        hb, state, budget, seen, stats, call_limit
    )
    return hb


def self_test():
    class Dummy:
        START = {'cycle': date(2011, 1, 1)}
    assert detail_url(2026, 39, 1, '광명', 16).endswith('/2026/39/1/001/16')
    assert detail_url(2026, 39, 1, '창원', 3).endswith('/2026/39/1/002/03')
    assert detail_url(2026, 39, 1, '부산', 4).endswith('/2026/39/1/004/04')

    cp = {'year': 2026, 'meeting': 39, 'day': 1}
    _step(cp, Dummy)
    assert cp == {'year': 2026, 'meeting': 38, 'day': 3}

    fixture = '''
    <h2>광명 16경주 (특선 18:56)</h2>
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
    d = _parse_detail(hb, fixture, '광명', 16, date(2026, 10, 2))
    assert d and len(d['runners']) == 7
    assert next(x for x in d['runners'] if x['number'] == 4)['final_rank'] == 1
    print('KCYCLE_EXACT_DETAIL_ROUTE_SELF_TEST=PASS')


if __name__ == '__main__' and '--self-test' in sys.argv:
    self_test()
