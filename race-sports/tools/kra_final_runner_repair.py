import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

from kra_official_enricher import DETAIL_URL, MEET_CODE, clean, fetch, parsed, venue_of

DATA = Path('race-sports/data/today.json')
KST = timezone(timedelta(hours=9))
PROVIDER = 'HORSE_FINAL_RUNNERS_KRA'


def _num(v):
    try:
        x = float(str(v).replace(',', '').replace('세', '').strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _idx(norm, *names):
    for name in names:
        if name in norm:
            return norm.index(name)
    return None


def parse_final_outcomes(raw):
    p, _ = parsed(raw)
    header = None
    out = []
    for row in p.rows:
        norm = [clean(x).replace(' ', '') for x in row]
        if '순위' in norm and '마번' in norm and '마명' in norm and '단승' in norm and '연승' in norm:
            header = {
                'rank': _idx(norm, '순위'),
                'number': _idx(norm, '마번'),
                'horse_name': _idx(norm, '마명'),
                'origin': _idx(norm, '산지'),
                'sex': _idx(norm, '성별'),
                'age': _idx(norm, '연령'),
                'weight': _idx(norm, '중량', '부담중량'),
                'jockey': _idx(norm, '기수명', '기수'),
                'trainer': _idx(norm, '조교사명', '조교사'),
                'owner': _idx(norm, '마주명', '마주'),
                'single': _idx(norm, '단승'),
                'place': _idx(norm, '연승'),
            }
            continue
        if not header:
            continue
        required = [header['rank'], header['number'], header['horse_name']]
        if any(i is None or i >= len(row) for i in required):
            continue
        rs = clean(row[header['rank']])
        ns = clean(row[header['number']])
        if not rs.isdigit() or not ns.isdigit():
            continue
        n = int(ns)
        name = clean(row[header['horse_name']])
        if not name or not 1 <= n <= 20:
            continue
        item = {
            'key': f'N{n}',
            'number': n,
            'name': f'{n} {name}',
            'horse_name': name,
            'model_p': None,
            'final_rank': int(rs),
            'final_odds_source': 'KRA_SCORETABLE_DETAIL_OFFICIAL',
        }
        for key in ('origin', 'sex', 'jockey', 'trainer', 'owner'):
            i = header.get(key)
            if i is not None and i < len(row):
                v = clean(row[i])
                if v:
                    item[key] = v
        i = header.get('age')
        if i is not None and i < len(row):
            v = _num(row[i])
            if v is not None:
                item['age'] = v
        i = header.get('weight')
        if i is not None and i < len(row):
            v = _num(row[i])
            if v is not None:
                item['assigned_weight'] = v
        i = header.get('single')
        if i is not None and i < len(row):
            v = _num(row[i])
            if v is not None:
                item['final_odds'] = v
        i = header.get('place')
        if i is not None and i < len(row):
            v = _num(row[i])
            if v is not None:
                item['final_place_odds'] = v
        out.append(item)
    out.sort(key=lambda x: x['number'])
    return out


def _preserve_pre_race(old, new):
    old_by = {o.get('key'): o for o in old if o.get('key')}
    keep = (
        'model_p', 'model_source', 'model_updated_at', 'model_state', 'model_validated',
        'odds', 'odds_source', 'odds_capture_mode', 'odds_observed_at',
    )
    for o in new:
        q = old_by.get(o.get('key'), {})
        for k in keep:
            if q.get(k) is not None:
                o[k] = q[k]
    return new


def _fetch_event(event, today):
    venue = venue_of(event)
    meet = MEET_CODE.get(venue)
    rn = int(event.get('race_no') or 0)
    if not meet or not rn:
        return event.get('id'), None, 'NO_MEET_OR_RACE'
    url = DETAIL_URL.format(meet=meet, date=today.replace('-', ''), race_no=rn)
    try:
        rows = parse_final_outcomes(fetch(url, timeout=10, retries=2))
        if len(rows) < 2:
            return event.get('id'), None, 'DETAIL_EMPTY'
        return event.get('id'), rows, None
    except Exception as exc:
        return event.get('id'), None, f'{type(exc).__name__}:{exc}'[:180]


def main():
    doc = json.loads(DATA.read_text(encoding='utf-8'))
    today = str(doc.get('date') or '')
    horse = [e for e in doc.get('events', []) if e.get('sport') == 'HORSE']
    final_events = [e for e in horse if e.get('status') == 'FINAL']

    # Remove runner rows supplied through an explicitly stale ChulmaDate page.
    # A later strict-date venue fetch may repopulate scheduled cards. Final
    # cards are rebuilt below from date-bound result-detail URLs.
    base = next((p for p in doc.get('providers', []) if p.get('provider') == 'HORSE_RUNNERS_KRA'), {})
    detail = base.get('detail') or {}
    page_date = detail.get('page_date')
    stale_runner_page = bool(page_date and page_date != today)
    cleared = 0
    if stale_runner_page:
        for e in horse:
            if e.get('outcomes'):
                e['outcomes'] = []
                cleared += 1

    by_id = {e.get('id'): e for e in final_events if e.get('id')}
    repaired = 0
    errors = []
    if final_events:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(_fetch_event, e, today) for e in final_events]
            for fut in as_completed(futures):
                event_id, rows, err = fut.result()
                e = by_id.get(event_id)
                if not e:
                    continue
                if rows:
                    e['outcomes'] = _preserve_pre_race(e.get('outcomes') or [], rows)
                    repaired += 1
                    result = e.get('result') or {}
                    top3 = []
                    for o in sorted(rows, key=lambda x: int(x.get('final_rank') or 999))[:3]:
                        top3.append({'rank': int(o['final_rank']), 'number': int(o['number']), 'name': o.get('horse_name') or str(o['number'])})
                    if result:
                        result['top3'] = top3
                        result['runner_identity_source'] = 'KRA_SCORETABLE_DETAIL_OFFICIAL'
                        e['result'] = result
                elif err:
                    errors.append(f'{event_id}:{err}')

    providers = doc.setdefault('providers', [])
    providers[:] = [p for p in providers if p.get('provider') != PROVIDER]
    status = 'PASS' if final_events and repaired == len(final_events) else ('PARTIAL' if repaired else ('NO_FINAL_CARD' if not final_events else 'FETCH_RETRY'))
    providers.append({
        'provider': PROVIDER,
        'status': status,
        'detail': {
            'date': today,
            'final_events': len(final_events),
            'repaired_events': repaired,
            'stale_runner_page_detected': stale_runner_page,
            'stale_outcomes_cleared': cleared,
            'source': 'KRA_SCORETABLE_DETAIL_OFFICIAL',
            'errors': errors[:5],
        },
    })
    doc['generated_at'] = datetime.now(KST).isoformat()
    DATA.write_text(json.dumps(doc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({'KRA_FINAL_RUNNER_REPAIR': status, 'repaired': repaired, 'final_events': len(final_events), 'cleared': cleared, 'errors': len(errors)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
