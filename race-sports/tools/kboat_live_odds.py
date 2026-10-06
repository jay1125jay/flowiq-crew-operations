import html, json, re, time, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
DATA = Path('race-sports/data/today.json')
BASES = [
    'https://kboat.or.kr/race/dividendrate/final',
    'https://www.kboat.or.kr/race/dividendrate/final',
]
UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'


def fetch_one(url, timeout=7):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=.9,en;q=.7',
        'Connection': 'close',
        'Cache-Control': 'no-cache',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'ignore')


def fetch_current():
    errors = []
    for url in BASES:
        try:
            return fetch_one(url), url
        except Exception as e:
            errors.append(f'{url}:{type(e).__name__}')
            time.sleep(.5)
    try:
        return fetch_one(BASES[0]), BASES[0]
    except Exception as e:
        errors.append(f'{BASES[0]}:{type(e).__name__}')
        raise RuntimeError(';'.join(errors)) from e


def textify(s):
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', html.unescape(s)).strip()


def parse_context(raw):
    u = html.unescape(raw)
    patterns = [
        r'fnRace\.popup\.result\(\s*["\'](\d{4})["\']\s*,\s*["\'](\d+)["\']\s*,\s*["\'](\d+)["\']\s*,\s*["\'](\d+)["\']\s*\)',
        r'fnSearchRace\(\s*["\']?(\d{4})["\']?\s*,\s*["\']?(\d+)["\']?\s*,\s*["\']?(\d+)["\']?\s*,\s*["\']?(\d+)["\']?\s*\)',
    ]
    for p in patterns:
        hits = list(re.finditer(p, u, re.I))
        if hits:
            y, tms, day, race = hits[-1].groups()
            return int(y), int(tms), int(day), int(race)
    return None


def parse_single(raw):
    h = re.search(r'<h3[^>]*>\s*단승식\s*</h3>', raw, re.I)
    if not h:
        return None
    sec = raw[h.end():h.end() + 8000]
    tb = re.search(r'<tbody[^>]*>([\s\S]*?)</tbody>', sec, re.I)
    if not tb:
        return None
    vals = []
    for cell in re.findall(r'<td[^>]*>([\s\S]*?)</td>', tb.group(1), re.I):
        m = re.search(r'(?<!\d)(\d+(?:\.\d+)?)(?!\d)', textify(cell).replace(',', ''))
        if m:
            vals.append(float(m.group(1)))
        if len(vals) >= 6:
            break
    return vals if len(vals) == 6 and all(v > 0 for v in vals) else None


def restore_capture_provenance(event):
    hist = event.get('odds_history') or []
    if not hist:
        return
    last = hist[-1]
    if last.get('source') != 'KBOAT_FINAL_SINGLE_AUTO':
        return
    mode = last.get('capture_mode')
    snap = last.get('odds') or {}
    if not mode:
        return
    for o in event.get('outcomes', []):
        key = o.get('key')
        if key in snap and float(o.get('odds', 0) or 0) == float(snap[key]):
            o['odds_capture_mode'] = mode


def apply(event, vals, observed_at, mode):
    snap = {f'N{i + 1}': float(vals[i]) for i in range(6)}
    hist = list(event.get('odds_history') or [])
    previous = hist[-1].get('odds', {}) if hist else {}
    previous_mode = hist[-1].get('capture_mode') if hist else None
    if previous != snap or previous_mode != mode:
        hist.append({
            'observed_at': observed_at,
            'market': '단승식',
            'source': 'KBOAT_FINAL_SINGLE_AUTO',
            'capture_mode': mode,
            'odds': snap,
        })
        event['odds_history'] = hist[-120:]
    for o in event.get('outcomes', []):
        n = int(o.get('number') or 0)
        if 1 <= n <= 6:
            o['odds'] = float(vals[n - 1])
            o['odds_source'] = 'KBOAT_FINAL_SINGLE_AUTO'
            o['odds_capture_mode'] = mode
            o['odds_observed_at'] = observed_at


def set_provider(payload, status, detail):
    providers = [p for p in payload.get('providers', []) if p.get('provider') != 'BOAT_LIVE_ODDS_KBOAT']
    providers.append({'provider': 'BOAT_LIVE_ODDS_KBOAT', 'status': status, 'detail': detail})
    payload['providers'] = providers


def main():
    payload = json.loads(DATA.read_text(encoding='utf-8'))
    now = datetime.now(KST)
    observed_at = now.isoformat()
    events = [e for e in payload.get('events', []) if e.get('sport') == 'BOAT']
    for event in events:
        restore_capture_provenance(event)

    payload['errors'] = [x for x in payload.get('errors', []) if not str(x).startswith('BOAT odds ')]

    # No BOAT card means there is nothing to join. Do not hit the live odds
    # endpoint just to discover that fact; it creates false FETCH_RETRY states
    # and wastes ~20 seconds on official-site network retries.
    if not events:
        detail = {
            'market': '단승식',
            'source': 'KBOAT_FINAL',
            'capture': 'CURRENT_PUBLISHED_RACE_ONLY',
            'active_pre_race_odds_events': 0,
            'reason': 'NO_TODAY_BOAT_EVENT',
        }
        set_provider(payload, 'NO_TODAY_CARD', detail)
        DATA.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        print(json.dumps({'status': 'NO_TODAY_CARD', **detail}, ensure_ascii=False))
        return

    status = 'WAITING'
    detail = {'market': '단승식', 'source': 'KBOAT_FINAL', 'capture': 'CURRENT_PUBLISHED_RACE_ONLY'}
    try:
        raw, source_url = fetch_current()
        ctx = parse_context(raw)
        vals = parse_single(raw)
        detail['source_url'] = source_url
        detail['context'] = ctx
        if ctx and vals:
            y, tms, day, race = ctx
            target = next((e for e in events if int(e.get('race_no') or 0) == race), None)
            detail['published_race'] = race
            detail['single_odds'] = vals
            detail['meeting'] = tms
            detail['day'] = day
            if target:
                detail['target_id'] = target.get('id')
                detail['target_status'] = target.get('status')
                detail['target_has_result'] = bool(target.get('result'))

            if target and target.get('status') == 'SCHEDULED' and not target.get('result'):
                apply(target, vals, observed_at, 'PRE_RACE_OFFICIAL')
                status = 'PASS'
                detail['captured_race'] = race
                detail['capture_mode'] = 'PRE_RACE_OFFICIAL'
            elif target and target.get('status') in ('LIVE', 'RESULT_PENDING') and not target.get('result'):
                apply(target, vals, observed_at, 'POST_START_OFFICIAL_CAPTURE')
                status = 'POST_START_CAPTURE'
                detail['captured_race'] = race
                detail['capture_mode'] = 'POST_START_OFFICIAL_CAPTURE'
            elif target and (target.get('status') == 'FINAL' or target.get('result')):
                has_history = bool(target.get('odds_history'))
                if not has_history:
                    apply(target, vals, observed_at, 'LATE_OFFICIAL_RECOVERY')
                    detail['recovered_race'] = race
                status = 'WAITING_NEXT_RACE'
                detail['reason'] = 'LATEST_PUBLISHED_RACE_ALREADY_FINAL'
            else:
                status = 'WAITING'
                detail['reason'] = 'PUBLISHED_RACE_NOT_FOUND_IN_TODAY_FEED'
        else:
            detail['reason'] = 'NO_CURRENT_OFFICIAL_SINGLE_ODDS'
    except Exception as e:
        status = 'FETCH_RETRY'
        detail['reason'] = str(e)[:240]

    active_odds = 0
    for e in events:
        if e.get('status') == 'SCHEDULED' and any(
            float(o.get('odds', 0) or 0) > 0 and o.get('odds_capture_mode') == 'PRE_RACE_OFFICIAL'
            for o in e.get('outcomes', [])
        ):
            active_odds += 1
    detail['active_pre_race_odds_events'] = active_odds

    set_provider(payload, status, detail)
    DATA.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({'status': status, **detail}, ensure_ascii=False))


if __name__ == '__main__':
    main()
