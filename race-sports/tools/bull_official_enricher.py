import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
DATA = Path('race-sports/data/today.json')
UA = 'Mozilla/5.0 (RACE SPORTS ANALYTICS GitHub official-readonly)'
ODDS_BASE = 'https://www.cpc.or.kr/cpc/module/game/gameRate/finalRate/index.do'
RESULT_BASE = 'https://www.cpc.or.kr/cpc/module/game/gameResult/view.do'


def fetch(url, timeout=15, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA,
                'Accept-Language': 'ko-KR,ko;q=.9',
                'Cache-Control': 'no-cache',
                'Connection': 'close',
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode('utf-8', 'ignore')
        except Exception as e:
            last = e
            if i + 1 < retries:
                time.sleep(1.2 * (i + 1))
    raise last


def textify(raw):
    s = re.sub(r'<script[\s\S]*?</script>', ' ', raw, flags=re.I)
    s = re.sub(r'<style[\s\S]*?</style>', ' ', s, flags=re.I)
    s = re.sub(r'<br\s*/?\s*>', '\n', s, flags=re.I)
    s = re.sub(r'</(tr|td|th|div|p|li|h1|h2|h3|h4|option)>', '\n', s, flags=re.I)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s).replace('\r', '')
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n[ \t]+', '\n', s)
    s = re.sub(r'\n{2,}', '\n', s)
    return s


def event_meta(e):
    m = re.match(r'BULL-(\d{8})-(\d+)-(\d+)-(\d+)$', str(e.get('id') or ''))
    if not m:
        return None
    ymd, rnd, day, race = m.groups()
    return {
        'year': int(ymd[:4]),
        'date': f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}',
        'round': int(rnd),
        'day': int(day),
        'race': int(race),
    }


def url_for(base, m):
    q = {
        'menu_idx': '56' if 'finalRate' in base else '54',
        'searchDayOrd': str(m['day']),
        'searchGameNo': f"{m['race']:02d}",
        'searchStndYear': str(m['year']),
        'searchTms': f"{m['round']:02d}",
    }
    return base + '?' + urllib.parse.urlencode(q)


def header_meta(text):
    m = re.search(r'(\d{4})년도\s*(\d+)회차\s*(\d+)일차\s*\((\d{2})월\s*(\d{2})일\)표', text)
    if not m:
        return None
    return {
        'year': int(m.group(1)),
        'round': int(m.group(2)),
        'day': int(m.group(3)),
        'date': f'{m.group(1)}-{m.group(4)}-{m.group(5)}',
    }


def parse_final_single(raw):
    text = textify(raw)
    hm = header_meta(text)
    # Prefer the single-win section. The official table is 홍 / 청 / 무.
    sec = text
    idx = sec.find('단승식 배당률')
    if idx >= 0:
        sec = sec[idx:idx + 2500]
    m = re.search(
        r'(?:구분\s*)?홍\s+청\s+무\s+배당률\s+'
        r'(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)',
        sec,
    )
    if not m:
        # Markup/text fallback.
        m = re.search(
            r'단승식[\s\S]{0,1200}?홍[\s\S]{0,80}?청[\s\S]{0,80}?무'
            r'[\s\S]{0,500}?(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)',
            sec,
        )
    odds = None if not m else {'RED': float(m.group(1)), 'BLUE': float(m.group(2)), 'DRAW': float(m.group(3))}
    red = blue = None
    x = re.search(r'출전\s*싸움소\s+([^\s\n]+)\s+([^\s\n]+)', text)
    if x:
        red, blue = x.group(1), x.group(2)
    return hm, odds, red, blue


def parse_result(raw):
    text = textify(raw)
    hm = header_meta(text)
    if '경기확정' not in text:
        return hm, None

    red = re.search(r'(?:^|\n)\s*홍\s+([^\s\n]+)\s+\[(승|패|무)\]', text)
    blue = re.search(r'(?:^|\n)\s*청\s+([^\s\n]+)\s+\[(승|패|무)\]', text)
    if not red or not blue:
        # More permissive fallback for table flattening.
        red = re.search(r'홍\s+([^\s\n]+)\s+\[(승|패|무)\]', text)
        blue = re.search(r'청\s+([^\s\n]+)\s+\[(승|패|무)\]', text)
    if not red or not blue:
        return hm, None

    if red.group(2) == '승':
        winner = 'RED'
    elif blue.group(2) == '승':
        winner = 'BLUE'
    elif red.group(2) == '무' or blue.group(2) == '무':
        winner = 'DRAW'
    else:
        return hm, None

    markets = []
    for market, win, odds in re.findall(r'(단승|시단승|복승|시복승)\s+([^\n]+?)\s+(\d+(?:\.\d+)?)\s*(?:\n|$)', text):
        markets.append({'market': market, 'winner': re.sub(r'\s+', ' ', win).strip(), 'odds': float(odds)})

    return hm, {
        'official': True,
        'status': 'CONFIRMED',
        'winner': {
            'key': winner,
            'label': {'RED': '홍', 'DRAW': '무', 'BLUE': '청'}[winner],
            'name': red.group(1) if winner == 'RED' else blue.group(1) if winner == 'BLUE' else '무승부',
        },
        'sides': {
            'RED': {'name': red.group(1), 'decision': red.group(2)},
            'BLUE': {'name': blue.group(1), 'decision': blue.group(2)},
        },
        'markets': markets,
        'source': 'CPC_RESULT_OFFICIAL',
    }


def set_provider(payload, name, status, detail):
    payload['providers'] = [p for p in payload.get('providers', []) if p.get('provider') != name]
    payload['providers'].append({'provider': name, 'status': status, 'detail': detail})


def apply_odds(e, odds, observed_at, source_url):
    if not odds:
        return False
    outcome_map = {o.get('key'): o for o in e.get('outcomes', [])}
    if not all(k in outcome_map for k in ('RED', 'DRAW', 'BLUE')):
        return False

    pre = e.get('status') == 'SCHEDULED' and not e.get('result')
    mode = 'PRE_RACE_OFFICIAL' if pre else 'LATE_OFFICIAL_RECOVERY'
    snap = {'RED': odds['RED'], 'DRAW': odds['DRAW'], 'BLUE': odds['BLUE']}
    hist = list(e.get('odds_history') or [])
    prev = hist[-1].get('odds', {}) if hist else {}
    if prev != snap:
        hist.append({
            'observed_at': observed_at,
            'market': '단승식',
            'source': 'CPC_FINAL_SINGLE_AUTO',
            'capture_mode': mode,
            'odds': snap,
            'source_url': source_url,
        })
        e['odds_history'] = hist[-120:]

    for key in ('RED', 'DRAW', 'BLUE'):
        o = outcome_map[key]
        o['odds'] = float(odds[key])
        o['odds_source'] = 'CPC_FINAL_SINGLE_AUTO'
        o['odds_capture_mode'] = mode
        o['odds_observed_at'] = observed_at
    return True


def apply_result(e, result, observed_at, source_url):
    if not result:
        return False
    result['updated_at'] = observed_at
    result['source_url'] = source_url
    e['result'] = result
    e['status'] = 'FINAL'
    winner = result.get('winner', {}).get('key')
    for o in e.get('outcomes', []):
        o['won'] = bool(winner and o.get('key') == winner)
    return True


def self_test():
    odds_meta = {'year': 2026, 'round': 33, 'day': 2, 'race': 11}
    result_meta = {'year': 2026, 'round': 19, 'day': 2, 'race': 2}
    oh, odds, red, blue = parse_final_single(fetch(url_for(ODDS_BASE, odds_meta)))
    rh, result = parse_result(fetch(url_for(RESULT_BASE, result_meta)))
    ok = bool(
        oh and oh['year'] == 2026 and oh['round'] == 33 and oh['day'] == 2 and
        odds and all(odds.get(k, 0) > 0 for k in ('RED', 'DRAW', 'BLUE')) and
        rh and rh['year'] == 2026 and rh['round'] == 19 and rh['day'] == 2 and
        result and result.get('winner', {}).get('key') in ('RED', 'DRAW', 'BLUE')
    )
    print(json.dumps({
        'SELF_TEST': 'PASS' if ok else 'FAIL',
        'odds_header': oh,
        'odds': odds,
        'odds_bulls': [red, blue],
        'result_header': rh,
        'winner': (result or {}).get('winner'),
    }, ensure_ascii=False))
    if not ok:
        raise SystemExit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return

    payload = json.loads(DATA.read_text(encoding='utf-8'))
    observed_at = datetime.now(KST).isoformat()
    bull = [e for e in payload.get('events', []) if e.get('sport') == 'BULL']
    odds_linked = 0
    results_linked = 0
    odds_errors = []
    result_errors = []

    for e in bull:
        m = event_meta(e)
        if not m:
            continue
        try:
            ou = url_for(ODDS_BASE, m)
            oh, odds, red, blue = parse_final_single(fetch(ou, timeout=12, retries=2))
            if oh and oh['date'] == m['date'] and oh['round'] == m['round'] and oh['day'] == m['day']:
                # Only accept a page that still refers to the same two bulls when names are available.
                same_names = True
                if red and e.get('left'):
                    same_names = same_names and re.sub(r'\s+', '', red) == re.sub(r'\s+', '', str(e.get('left')))
                if blue and e.get('right'):
                    same_names = same_names and re.sub(r'\s+', '', blue) == re.sub(r'\s+', '', str(e.get('right')))
                if same_names and apply_odds(e, odds, observed_at, ou):
                    odds_linked += 1
        except Exception as x:
            odds_errors.append(f"{e.get('id')}:{type(x).__name__}:{x}"[:220])

        try:
            ru = url_for(RESULT_BASE, m)
            rh, result = parse_result(fetch(ru, timeout=12, retries=2))
            if rh and rh['date'] == m['date'] and rh['round'] == m['round'] and rh['day'] == m['day']:
                if apply_result(e, result, observed_at, ru):
                    results_linked += 1
        except Exception as x:
            result_errors.append(f"{e.get('id')}:{type(x).__name__}:{x}"[:220])

    set_provider(
        payload,
        'BULL_LIVE_ODDS_CPC',
        'PASS' if odds_linked else ('NO_TODAY_CARD' if not bull else 'WAITING'),
        {
            'market': '단승식',
            'capture': 'official final odds after sales close',
            'linked': odds_linked,
            'errors': odds_errors[-5:],
            'source': ODDS_BASE,
        },
    )
    set_provider(
        payload,
        'BULL_RESULT_CPC',
        'PASS' if results_linked else ('NO_TODAY_CARD' if not bull else 'WAITING'),
        {
            'confirmed': results_linked,
            'errors': result_errors[-5:],
            'source': RESULT_BASE,
        },
    )

    DATA.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({
        'BULL_OFFICIAL_ENRICH': 'PASS',
        'events': len(bull),
        'odds_linked': odds_linked,
        'results_linked': results_linked,
        'odds_errors': len(odds_errors),
        'result_errors': len(result_errors),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
