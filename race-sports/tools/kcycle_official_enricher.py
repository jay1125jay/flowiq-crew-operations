import html
import json
import math
import re
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path

KST = timezone(timedelta(hours=9))
DATA = Path('race-sports/data/today.json')
UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'
AI_URL = 'https://www.kcycle.or.kr/rankingpredict'
ODDS_URL = 'https://www.kcycle.or.kr/race/dividendrate/final'
RESULT_URL = 'https://www.kcycle.or.kr/race/result/general'
VENUES = ('광명', '창원', '부산')


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_tr = False
        self.in_cell = False
        self.cell = []
        self.row = []
        self.rows = []
        self.text_parts = []
        self.selected = False
        self.option = []
        self.selected_options = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs)
        if tag == 'tr':
            self.in_tr = True
            self.row = []
        elif tag in ('td', 'th') and self.in_tr:
            self.in_cell = True
            self.cell = []
        elif tag == 'option':
            self.selected = 'selected' in attrs or attrs.get('selected') is not None
            self.option = []
        if tag in ('br', 'p', 'div', 'h1', 'h2', 'h3', 'h4', 'li'):
            self.text_parts.append('\n')

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ('td', 'th') and self.in_cell:
            self.row.append(clean(''.join(self.cell)))
            self.in_cell = False
            self.cell = []
        elif tag == 'tr' and self.in_tr:
            if self.row:
                self.rows.append(self.row[:])
            self.in_tr = False
            self.row = []
        elif tag == 'option':
            if self.selected:
                self.selected_options.append(clean(''.join(self.option)))
            self.selected = False
            self.option = []
        if tag in ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'li', 'tr'):
            self.text_parts.append('\n')

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)
        if self.selected:
            self.option.append(data)
        self.text_parts.append(data)

    def text(self):
        s = html.unescape(''.join(self.text_parts)).replace('\r', '')
        s = re.sub(r'[ \t]+', ' ', s)
        s = re.sub(r'\n[ \t]+', '\n', s)
        return re.sub(r'\n{2,}', '\n', s)


def clean(s):
    return re.sub(r'\s+', ' ', html.unescape(str(s))).strip()


def fetch(url, timeout=12, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=.9,en;q=.7',
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


def parsed(raw):
    p = TableParser()
    p.feed(raw)
    return p, p.text()


def page_date(text, parser=None):
    pats = [
        r'(\d{4})[-./](\d{2})[-./](\d{2})(?:\s+\d{1,2}:\d{2}:\d{2})?\s*기준',
        r'(\d{4})년\s*\d+회\s*\d+일차\s*\((\d{2})월\s*(\d{2})일\)',
        r'(\d{4})[-./](\d{2})[-./](\d{2})',
    ]
    for pat in pats:
        m = re.search(pat, text)
        if m:
            return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    if parser:
        for opt in parser.selected_options:
            m = re.search(r'(\d{4})[-./](\d{2})[-./](\d{2})', opt)
            if m:
                return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
            m = re.search(r'(\d{2})월\s*(\d{2})일', opt)
            if m:
                y = datetime.now(KST).year
                return f'{y}-{m.group(1)}-{m.group(2)}'
    return None


def event_key(venue, race_no):
    return venue, int(race_no)


def parse_ai(raw):
    p, text = parsed(raw)
    date = page_date(text, p)
    out = {}
    for row in p.rows:
        if not row:
            continue
        m = re.search(r'(광명|창원|부산)\s*0?(\d{1,2})(?:경주)?', row[0])
        if not m:
            continue
        joined = ' '.join(row[1:])
        pairs = re.findall(r'(?<!\d)([1-7])\s+(\d+(?:\.\d+)?)\s*%', joined)
        if len(pairs) < 5:
            continue
        probs = {int(n): float(v) / 100.0 for n, v in pairs}
        s = sum(probs.values())
        if 0.98 <= s <= 1.02:
            out[event_key(m.group(1), m.group(2))] = probs
    if not out:
        for m in re.finditer(r'(광명|창원|부산)\s*0?(\d{1,2})\s+((?:[1-7]\s+\d+(?:\.\d+)?%\s*){5,7})', text):
            pairs = re.findall(r'([1-7])\s+(\d+(?:\.\d+)?)%', m.group(3))
            probs = {int(n): float(v) / 100.0 for n, v in pairs}
            if len(probs) >= 5:
                out[event_key(m.group(1), m.group(2))] = probs
    return date, out


def parse_winner(cell):
    m = re.search(r'([1-7])\s*([가-힣]{2,5})', clean(cell))
    return {'number': int(m.group(1)), 'name': m.group(2)} if m else None


def parse_market_cell(cell, market):
    vals = []
    for winner, odds in re.findall(r'\(([^)]+)\)\s*(\d+(?:\.\d+)?)', clean(cell)):
        vals.append({'market': market, 'winner': winner.replace(' ', ''), 'odds': float(odds)})
    return vals


def parse_results(raw):
    p, text = parsed(raw)
    date = page_date(text, p)
    out = {}
    markets = ['단승식', '연승식', '쌍승식', '복승식', '삼복승식', '쌍복승식', '삼쌍승식']
    for row in p.rows:
        if len(row) < 4:
            continue
        m = re.search(r'(광명|창원|부산)\s*0?(\d{1,2})', row[0])
        if not m:
            continue
        top = [parse_winner(x) for x in row[1:4]]
        if any(x is None for x in top):
            continue
        top3 = [{'rank': i + 1, **top[i]} for i in range(3)]
        pays = []
        for i, cell in enumerate(row[4:11]):
            if i < len(markets):
                pays.extend(parse_market_cell(cell, markets[i]))
        out[event_key(m.group(1), m.group(2))] = {
            'official': True,
            'status': 'CONFIRMED',
            'top3': top3,
            'markets': pays,
            'source': 'KCYCLE_RESULT_OFFICIAL',
            'source_url': RESULT_URL,
        }
    return date, out


def valid_single_odds(vals):
    if not vals or len(vals) != 7:
        return False
    try:
        xs=[float(x) for x in vals]
    except Exception:
        return False
    if any((not math.isfinite(x)) or x <= 0 or x > 10000 for x in xs):
        return False
    # KCYCLE tables place the lane header 1..7 next to the actual odds row.
    # Never treat that header sequence itself as market odds.
    if all(abs(xs[i] - float(i + 1)) < 1e-9 for i in range(7)):
        return False
    return True


def parse_single_odds(raw):
    p, text = parsed(raw)
    date = page_date(text, p)
    contexts = list(re.finditer(r'(광명|창원|부산)\s*0?(\d{1,2})경주\s*\([^)]*?(\d{1,2})\s*:\s*(\d{2})\)', text))
    if not contexts:
        contexts = list(re.finditer(r'(광명|창원|부산)\s*0?(\d{1,2})경주', text))
    if not contexts:
        return date, None, None
    c = contexts[-1]
    key = event_key(c.group(1), c.group(2))
    vals = None
    for i, row in enumerate(p.rows):
        joined = ' '.join(row)
        if '단승식' in joined:
            for rr in p.rows[i:i + 4]:
                nums = []
                for x in rr:
                    if re.fullmatch(r'\d+(?:\.\d+)?', clean(x)):
                        nums.append(float(clean(x)))
                if len(nums) >= 7:
                    cand = nums[-7:]
                    if valid_single_odds(cand):
                        vals = cand
                        break
        if vals:
            break
    if vals is None:
        odds_token = r'(\d+(?:\.\d+)?)'
        m = re.search(r'단승식\s+1\s+2\s+3\s+4\s+5\s+6\s+7\s+' + r'\s+'.join([odds_token] * 7), text)
        if m:
            cand = [float(x) for x in m.groups()]
            vals = cand if valid_single_odds(cand) else None
    return date, key, vals


def venue_from_event(e):
    c = str(e.get('competition') or '') + ' ' + str(e.get('title') or '')
    return next((v for v in VENUES if v in c), None)


def set_provider(payload, name, status, detail):
    payload['providers'] = [p for p in payload.get('providers', []) if p.get('provider') != name]
    payload['providers'].append({'provider': name, 'status': status, 'detail': detail})


def apply_ai(payload, raw, observed_at):
    date, models = parse_ai(raw)
    today = payload.get('date')
    linked = 0
    if date == today:
        for e in payload.get('events', []):
            if e.get('sport') != 'CYCLE':
                continue
            venue = venue_from_event(e)
            probs = models.get(event_key(venue, e.get('race_no'))) if venue else None
            if not probs:
                continue
            for o in e.get('outcomes', []):
                n = int(o.get('number') or 0)
                if n in probs:
                    o['model_p'] = probs[n]
                    o['model_source'] = 'KCYCLE_AI_OFFICIAL'
                    o['model_updated_at'] = observed_at
            linked += 1
    set_provider(payload, 'CYCLE_AI_KCYCLE', 'PASS' if linked else ('NO_TODAY_CARD' if not any(e.get('sport') == 'CYCLE' for e in payload.get('events', [])) else 'STALE_OR_UNLINKED'), {'page_date': date, 'races_parsed': len(models), 'linked': linked, 'source_url': AI_URL, 'meaning': 'official AI rider win probability'})
    return linked


def apply_results(payload, raw, observed_at):
    date, results = parse_results(raw)
    today = payload.get('date')
    linked = 0
    if date == today:
        for e in payload.get('events', []):
            if e.get('sport') != 'CYCLE':
                continue
            venue = venue_from_event(e)
            r = results.get(event_key(venue, e.get('race_no'))) if venue else None
            if not r:
                continue
            r['updated_at'] = observed_at
            e['result'] = r
            e['status'] = 'FINAL'
            for o in e.get('outcomes', []):
                hit = next((x for x in r['top3'] if x['number'] == o.get('number')), None)
                if hit:
                    o['final_rank'] = hit['rank']
            linked += 1
    set_provider(payload, 'CYCLE_RESULT_KCYCLE', 'PASS' if linked else ('NO_TODAY_CARD' if not any(e.get('sport') == 'CYCLE' for e in payload.get('events', [])) else 'WAITING'), {'page_date': date, 'results_parsed': len(results), 'confirmed': linked, 'source_url': RESULT_URL})
    return linked


def apply_odds(payload, raw, observed_at):
    date, key, vals = parse_single_odds(raw)
    today = payload.get('date')
    captured = 0
    target = None
    if key and valid_single_odds(vals) and (date is None or date == today):
        for e in payload.get('events', []):
            if e.get('sport') != 'CYCLE':
                continue
            venue = venue_from_event(e)
            if venue and event_key(venue, e.get('race_no')) == key:
                target = e
                break
        if target and target.get('status') == 'SCHEDULED' and not target.get('result'):
            snap = {f'N{i + 1}': float(vals[i]) for i in range(7)}
            hist = list(target.get('odds_history') or [])
            prev = hist[-1].get('odds', {}) if hist else {}
            if prev != snap:
                hist.append({'observed_at': observed_at, 'market': '단승식', 'source': 'KCYCLE_FINAL_SINGLE_AUTO', 'capture_mode': 'PRE_RACE_OFFICIAL', 'odds': snap})
                target['odds_history'] = hist[-120:]
            for o in target.get('outcomes', []):
                n = int(o.get('number') or 0)
                if 1 <= n <= 7:
                    o['odds'] = vals[n - 1]
                    o['odds_source'] = 'KCYCLE_FINAL_SINGLE_AUTO'
                    o['odds_capture_mode'] = 'PRE_RACE_OFFICIAL'
                    o['odds_observed_at'] = observed_at
            captured = 1
    set_provider(payload, 'CYCLE_LIVE_ODDS_KCYCLE', 'PASS' if captured else 'WAITING', {'page_date': date, 'context': list(key) if key else None, 'single_odds': vals, 'captured': captured, 'target_id': target.get('id') if target else None, 'source_url': ODDS_URL})
    return captured


def main():
    payload = json.loads(DATA.read_text(encoding='utf-8'))
    observed_at = datetime.now(KST).isoformat()
    statuses = {}
    for name, url, fn in [('results', RESULT_URL, apply_results), ('ai', AI_URL, apply_ai), ('odds', ODDS_URL, apply_odds)]:
        try:
            raw = fetch(url)
            statuses[name] = fn(payload, raw, observed_at)
        except Exception as e:
            set_provider(payload, f'CYCLE_{name.upper()}_KCYCLE', 'FETCH_RETRY', {'error': f'{type(e).__name__}:{e}'[:220], 'source_url': url})
            statuses[name] = 'FETCH_RETRY'
    DATA.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({'KCYCLE_ENRICH': 'PASS', **statuses}, ensure_ascii=False))


if __name__ == '__main__':
    main()
