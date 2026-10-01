import re
import sys
import urllib.error
from datetime import date


def _clean(hb, value):
    return hb.clean(value) if value is not None else ''


def _horse_candidate_valid(hb, outcome):
    name = str(outcome.get('horse_name') or '').strip()
    if not name or '코너지점' in name or name in {'마명', '순위', '마번'}:
        return False
    if len(name) > 40:
        return False

    num = outcome.get('number')
    rank = outcome.get('final_rank')
    try:
        if not 1 <= int(num) <= 20 or not 1 <= int(rank) <= 20:
            return False
    except Exception:
        return False

    sex = str(outcome.get('sex') or '').strip()
    if sex and sex not in {'수', '암', '거'}:
        return False

    age = outcome.get('age')
    if age is not None:
        try:
            if not 1 <= int(age) <= 20:
                return False
        except Exception:
            return False

    weight = outcome.get('assigned_weight')
    if weight is not None:
        try:
            if not 35.0 <= float(weight) <= 70.0:
                return False
        except Exception:
            return False

    for key in ('jockey', 'trainer'):
        value = str(outcome.get(key) or '').strip()
        if value and ('F-G' in value or '코너지점' in value or value in {'기수명', '조교사명'}):
            return False
    return True


def _parse_horse_detail(hb, raw, meet, d, race_no):
    p, text = hb.parse_html(raw)

    # KRA occasionally returns a usable HTML page even when the requested
    # historical race is not the page actually rendered. Never label a race
    # unless visible metadata agrees with the requested date/race when present.
    meta = re.search(
        r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일[\s\S]{0,1800}?제\s*(\d{1,2})경주',
        text,
    )
    race_info = {}
    if meta:
        rendered = date(int(meta.group(1)), int(meta.group(2)), int(meta.group(3)))
        rendered_race = int(meta.group(4))
        if rendered != d or rendered_race != int(race_no):
            return None
        segment = text[meta.start():meta.start() + 2500]
        tm = re.search(r'(?:출발|발주)[^0-9]{0,20}(\d{1,2}:\d{2})', segment)
        if tm:
            race_info['start_time'] = tm.group(1)

    header = None
    candidates = []
    for row in p.rows:
        norm = [_clean(hb, x).replace(' ', '') for x in row]
        if all(k in norm for k in ('순위', '마번', '마명', '기수명', '조교사명', '단승')):
            def idx(k):
                try:
                    return norm.index(k)
                except ValueError:
                    return None
            header = {
                'rank': idx('순위'), 'number': idx('마번'), 'horse_name': idx('마명'),
                'origin': idx('산지'), 'sex': idx('성별'), 'age': idx('연령'),
                'weight': idx('중량'), 'rating': idx('레이팅'), 'jockey': idx('기수명'),
                'trainer': idx('조교사명'), 'owner': idx('마주명'),
                'single': idx('단승'), 'place': idx('연승'),
            }
            continue
        if not header:
            continue
        required = [header['rank'], header['number'], header['horse_name']]
        if any(i is None for i in required) or len(row) <= max(required):
            continue

        rank = hb.as_int(row[header['rank']])
        number = hb.as_int(row[header['number']])
        if rank is None or number is None:
            continue

        def val(key):
            i = header.get(key)
            return _clean(hb, row[i]) if i is not None and i < len(row) else None

        outcome = {
            'key': f'N{int(number)}',
            'number': int(number),
            'horse_name': val('horse_name'),
            'name': f'{int(number)} {val("horse_name")}',
            'origin': val('origin'),
            'sex': val('sex'),
            'age': hb.as_int(val('age')),
            'assigned_weight': hb.as_float(val('weight')),
            'rating': hb.as_float(val('rating')),
            'jockey': val('jockey'),
            'trainer': val('trainer'),
            'owner': val('owner'),
            'final_rank': int(rank),
            'won': int(rank) == 1,
            'final_odds': hb.as_float(val('single')),
            'final_place_odds': hb.as_float(val('place')),
        }
        if _horse_candidate_valid(hb, outcome):
            candidates.append(outcome)

    # Race-level quality gate BEFORE persistence. This is intentionally strict:
    # questionable historical KRA HTML is skipped and retried rather than used.
    by_number = {}
    for o in candidates:
        by_number.setdefault(o['number'], o)
    rows = list(by_number.values())
    rows.sort(key=lambda x: x['number'])
    if len(rows) < 5:
        return None
    if len({o['final_rank'] for o in rows}) != len(rows):
        return None
    if sum(1 for o in rows if o['won']) != 1:
        return None
    if len({o['horse_name'] for o in rows}) != len(rows):
        return None

    meet_name = {'1': '서울', '2': '제주', '3': '부경', '4': '영천'}.get(str(meet), str(meet))
    return {
        'id': f'HORSE-{d.strftime("%Y%m%d")}-M{meet}-{int(race_no):02d}',
        'sport': 'HORSE', 'provider': 'KRA', 'competition': f'{meet_name} 경마',
        'event_date': d.isoformat(), 'race_no': int(race_no), 'status': 'FINAL',
        'start_time': race_info.get('start_time'), 'market_type': 'RUNNERS',
        'outcomes': rows,
        'result': {
            'official': True, 'status': 'CONFIRMED',
            'winner_number': next(o['number'] for o in rows if o['won']),
            'source': 'KRA_SCORETABLE_DETAIL_OFFICIAL',
        },
        'feature_contract': {
            'allowed_prerace_fields': ['horse_name', 'origin', 'sex', 'age', 'assigned_weight', 'rating', 'jockey', 'trainer', 'owner'],
            'blocked_postrace_fields': ['final_rank', 'won', 'final_odds', 'final_place_odds'],
            'source_note': 'stable race-entry fields read from official final scoretable; labels kept separately; strict rendered-race and row quality validation',
        },
        'source_url': hb.HORSE_DETAIL.format(meet=meet, ymd=d.strftime('%Y%m%d'), race=race_no),
    }


def _advance_cycle(hb, state, stats):
    stats['cycle_dates'] += 1
    hb.advance_day(state['checkpoints'], 'cycle', hb.START['cycle'])
    hb.save_state(state)


def _is_404(exc):
    return isinstance(exc, urllib.error.HTTPError) and int(getattr(exc, 'code', 0)) == 404


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
            _advance_cycle(hb, state, stats)
            continue

        iso = d.isocalendar()
        day = {4: 1, 5: 2, 6: 3}[d.weekday()]
        card_url = hb.CYCLE_CARD.format(year=iso.year, week=iso.week, day=day)
        try:
            card_raw = hb.fetch(card_url, budget, 'ksports', timeout=10, retries=1)
        except Exception as exc:
            if _is_404(exc):
                # No KCYCLE meeting for this calendar date. This is not a
                # transient provider failure and must never pin the checkpoint.
                _advance_cycle(hb, state, stats)
                continue
            stats['errors'].append(f'CYCLE {d} CARD {type(exc).__name__}:{exc}'[:220])
            break

        page_day = hb.selected_date(card_raw, d.year)
        if page_day is not None and page_day != d:
            stats['errors'].append(f'CYCLE {d} CARD_DATE_MISMATCH:{page_day}'[:220])
            _advance_cycle(hb, state, stats)
            continue

        card = hb.parse_cycle_card(card_raw, d)
        if not card:
            _advance_cycle(hb, state, stats)
            continue
        if not room(1):
            break

        result_url = hb.CYCLE_RESULT.format(year=iso.year, week=iso.week, day=day)
        try:
            result_raw = hb.fetch(result_url, budget, 'ksports', timeout=10, retries=1)
        except Exception as exc:
            if _is_404(exc):
                stats['errors'].append(f'CYCLE {d} RESULT_404_SKIPPED'[:220])
                _advance_cycle(hb, state, stats)
                continue
            stats['errors'].append(f'CYCLE {d} RESULT {type(exc).__name__}:{exc}'[:220])
            break

        result_day = hb.selected_date(result_raw, d.year)
        if result_day is not None and result_day != d:
            stats['errors'].append(f'CYCLE {d} RESULT_DATE_MISMATCH:{result_day}'[:220])
            _advance_cycle(hb, state, stats)
            continue

        results = hb.parse_cycle_results(result_raw)
        if not results:
            stats['errors'].append(f'CYCLE {d} RESULT_EMPTY_SKIPPED'[:220])
            _advance_cycle(hb, state, stats)
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
                'source_url': result_url,
            }
            hb.append_record('cycle', event)
            seen.add(event_id)
            stats['cycle_records'] += 1

        _advance_cycle(hb, state, stats)


def install(hb):
    hb.parse_horse_detail = lambda raw, meet, d, race_no: _parse_horse_detail(hb, raw, meet, d, race_no)
    hb.backfill_cycle = lambda state, budget, seen, stats, call_limit=None: _backfill_cycle(hb, state, budget, seen, stats, call_limit)
    return hb


def self_test():
    import historical_backfill as hb
    install(hb)
    rows = []
    names = ['가라가라가', '새벽장군', '청룡스타', '한강대로', '금빛질주']
    for i, name in enumerate(names, 1):
        rows.append(
            f'<tr><td>{i}</td><td>{i}</td><td>{name}</td><td>한</td><td>수</td><td>3세</td>'
            f'<td>{55 + (i % 2)}</td><td>{30+i}</td><td>기수{i}</td><td>조교사{i}</td><td>마주{i}</td>'
            f'<td></td><td>450</td><td>{2.0+i}</td><td>{1.0+i/10}</td></tr>'
        )
    fixture = (
        '<div>2026년 09월 27일 제 1경주 출발 10:40</div><table>'
        '<tr><th>순위</th><th>마번</th><th>마명</th><th>산지</th><th>성별</th><th>연령</th>'
        '<th>중량</th><th>레이팅</th><th>기수명</th><th>조교사명</th><th>마주명</th>'
        '<th>도착차</th><th>마체중</th><th>단승</th><th>연승</th></tr>'
        + ''.join(rows) + '</table>'
    )
    good = hb.parse_horse_detail(fixture, '1', date(2026, 9, 27), 1)
    assert good and len(good['outcomes']) == 5 and sum(o['won'] for o in good['outcomes']) == 1
    assert hb.parse_horse_detail(fixture, '1', date(2026, 9, 26), 1) is None
    bad = fixture.replace('가라가라가', '1코너지점')
    assert hb.parse_horse_detail(bad, '1', date(2026, 9, 27), 1) is None
    print('HISTORICAL_BACKFILL_HARDENING_SELF_TEST=PASS')


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        self_test()
