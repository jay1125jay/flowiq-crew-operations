import argparse
import html
import json
import re
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path

KST = timezone(timedelta(hours=9))
DATA = Path('race-sports/data/today.json')
UA = 'Mozilla/5.0 (RACE SPORTS ANALYTICS GitHub official-readonly)'
BASE = 'https://www.cpc.or.kr/cpc/module/game/gameCard/confirmed/index.do?menu_idx=52'


class RowParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_tr = False
        self.in_cell = False
        self.cell = []
        self.row = []
        self.rows = []
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == 'tr':
            self.in_tr = True
            self.row = []
        if tag in ('td', 'th') and self.in_tr:
            self.in_cell = True
            self.cell = []
        if tag in ('br', 'p', 'div', 'h1', 'h2', 'h3', 'h4', 'li'):
            self.text_parts.append('\n')

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ('td', 'th') and self.in_cell:
            txt = re.sub(r'\s+', ' ', ''.join(self.cell)).strip()
            self.row.append(txt)
            self.in_cell = False
            self.cell = []
        if tag == 'tr' and self.in_tr:
            if self.row:
                self.rows.append(self.row[:])
            self.in_tr = False
            self.row = []
        if tag in ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'li', 'tr'):
            self.text_parts.append('\n')

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)
        self.text_parts.append(data)

    def text(self):
        s = html.unescape(''.join(self.text_parts)).replace('\r', '')
        s = re.sub(r'[ \t]+', ' ', s)
        s = re.sub(r'\n[ \t]+', '\n', s)
        s = re.sub(r'\n{2,}', '\n', s)
        return s


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
                time.sleep(1.5 * (i + 1))
    raise last


def pct_value(s):
    m = re.search(r'(-?\d+(?:\.\d+)?)\s*%', str(s))
    return float(m.group(1)) / 100.0 if m else None


def record3(s):
    m = re.search(r'(\d+)\s*/\s*(\d+)\s*/\s*(\d+)', str(s))
    return tuple(map(int, m.groups())) if m else None


def pair_record(s):
    m = re.fullmatch(r'\s*(\d+)\s*/\s*(\d+)\s*', str(s))
    return tuple(map(int, m.groups())) if m else None


def weight_value(s):
    m = re.search(r'(?<!\d)(\d{3,4})(?:\s*\(|$)', str(s))
    if not m:
        return None
    v = int(m.group(1))
    return float(v) if 300 <= v <= 1500 else None


def parse_rows(raw):
    p = RowParser()
    p.feed(raw)
    rows = [[re.sub(r'\s+', ' ', c).strip() for c in row] for row in p.rows]
    return p.text(), rows


def all_name_rows(rows):
    out = {}
    for row in rows:
        if len(row) < 2 or row[0] not in ('홍', '청'):
            continue
        name = re.sub(r'\s+', '', row[1])
        if not name:
            continue
        out.setdefault((row[0], name), []).append(row)
    return out


def recent_summary(rows):
    joined = ' '.join(' '.join(r) for r in rows)
    wins = len(re.findall(r'\[승\]', joined))
    draws = len(re.findall(r'\[무\]', joined))
    losses = len(re.findall(r'\[패\]', joined))
    n = wins + draws + losses
    return {
        'recent_wins': wins,
        'recent_draws': draws,
        'recent_losses': losses,
        'bull_recent_win_rate': wins / n if n else None,
    }


def extract_features(side, name, rows):
    rr = rows.get((side, re.sub(r'\s+', '', name)), [])
    f = {
        'age': None,
        'career_win_rate': None,
        'career_wins': None,
        'career_draws': None,
        'career_losses': None,
        'bull_recent_win_rate': None,
        'head_to_head_win_rate': None,
        'head_to_head_wins': None,
        'head_to_head_meetings': None,
        'trainer_recent_win_rate': None,
        'trainer_wins': None,
        'trainer_meetings': None,
        'weight': None,
        'rest_days': None,
        'bull_rating': None,
    }
    for row in rr:
        if len(row) >= 3 and f['age'] is None and re.fullmatch(r'\d{1,2}', row[2] or ''):
            age = int(row[2])
            if 1 <= age <= 30:
                f['age'] = float(age)
        if f['career_win_rate'] is None:
            for c in row:
                v = pct_value(c)
                if v is not None:
                    f['career_win_rate'] = v
                    break
        if f['career_wins'] is None:
            for c in row:
                rec = record3(c)
                if rec:
                    f['career_wins'], f['career_draws'], f['career_losses'] = rec
                    break
        if f['weight'] is None:
            for c in reversed(row):
                v = weight_value(c)
                if v is not None:
                    f['weight'] = v
                    break

        pairs = [pair_record(c) for c in row]
        pairs = [x for x in pairs if x]
        # Match-up table contains bull H2H first and trainer W/starts later.
        if pairs:
            if f['head_to_head_meetings'] is None:
                w, n = pairs[0]
                if n >= w:
                    f['head_to_head_wins'] = w
                    f['head_to_head_meetings'] = n
                    f['head_to_head_win_rate'] = w / n if n else 0.0
            if len(pairs) >= 2 and f['trainer_meetings'] is None:
                w, n = pairs[1]
                if n >= w and n > 0:
                    f['trainer_wins'] = w
                    f['trainer_meetings'] = n
                    f['trainer_recent_win_rate'] = w / n

    r = recent_summary(rr)
    if r['bull_recent_win_rate'] is not None:
        f.update(r)
    return f


def parse_card(raw):
    text, table_rows = parse_rows(raw)
    hdr = re.search(r'(\d{4})년도\s*(\d+)회차\s*(\d+)일차\s*\((\d{2})월\s*(\d{2})일\)표', text)
    meta = None
    if hdr:
        meta = {
            'year': int(hdr.group(1)),
            'round': int(hdr.group(2)),
            'day': int(hdr.group(3)),
            'date': f'{hdr.group(1)}-{hdr.group(4)}-{hdr.group(5)}',
        }
    rowmap = all_name_rows(table_rows)
    matches = []
    headers = list(re.finditer(r'(\d{2})경기\s*([갑을병])?\s*\(시작시간:\s*([^)]+)\)', text))
    for i, m in enumerate(headers):
        seg = text[m.end():(headers[i + 1].start() if i + 1 < len(headers) else len(text))]
        red = re.search(r'(?:^|\n)\s*홍\s+([^\s\n]+)', seg)
        blue = re.search(r'(?:^|\n)\s*청\s+([^\s\n]+)', seg)
        if not red or not blue:
            continue
        red_name, blue_name = red.group(1).strip(), blue.group(1).strip()
        q = re.search(r'(\d{1,2})\s*[:시]\s*(\d{1,2})', m.group(3))
        tm = f'{int(q.group(1)):02d}:{int(q.group(2)):02d}' if q else None
        rf = extract_features('홍', red_name, rowmap)
        bf = extract_features('청', blue_name, rowmap)
        if rf.get('weight') is not None and bf.get('weight') is not None:
            rf['weight_diff'] = rf['weight'] - bf['weight']
            bf['weight_diff'] = bf['weight'] - rf['weight']
        else:
            rf['weight_diff'] = None
            bf['weight_diff'] = None
        matches.append({
            'race_no': int(m.group(1)),
            'grade': m.group(2),
            'start_time': tm,
            'red_name': red_name,
            'blue_name': blue_name,
            'red_features': rf,
            'blue_features': bf,
        })
    return meta, matches


def enrich_payload(payload, raw, source_url):
    meta, matches = parse_card(raw)
    by_no = {m['race_no']: m for m in matches}
    linked = 0
    for e in payload.get('events', []):
        if e.get('sport') != 'BULL':
            continue
        m = by_no.get(int(e.get('race_no') or 0))
        if not m:
            continue
        if e.get('left') and re.sub(r'\s+', '', e['left']) != re.sub(r'\s+', '', m['red_name']):
            continue
        if e.get('right') and re.sub(r'\s+', '', e['right']) != re.sub(r'\s+', '', m['blue_name']):
            continue
        e['bull_features'] = {
            'RED': m['red_features'],
            'BLUE': m['blue_features'],
            'pair': {
                'red_name': m['red_name'],
                'blue_name': m['blue_name'],
                'grade': m['grade'],
            },
        }
        e['bull_feature_source'] = 'CPC_CONFIRMED_CARD_OFFICIAL'
        linked += 1
    providers = [p for p in payload.get('providers', []) if p.get('provider') != 'BULL_FEATURES_CPC']
    providers.append({
        'provider': 'BULL_FEATURES_CPC',
        'status': 'PASS' if linked else ('NO_TODAY_CARD' if not any(e.get('sport') == 'BULL' for e in payload.get('events', [])) else 'UNLINKED'),
        'detail': {
            'linked': linked,
            'parsed_matches': len(matches),
            'card': meta,
            'source_url': source_url,
        },
    })
    payload['providers'] = providers
    return linked, len(matches), meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--self-test-url')
    args = ap.parse_args()
    if args.self_test_url:
        raw = fetch(args.self_test_url)
        meta, matches = parse_card(raw)
        rich = sum(1 for m in matches if m['red_features'].get('age') is not None and m['blue_features'].get('age') is not None)
        weights = sum(1 for m in matches if m['red_features'].get('weight') is not None and m['blue_features'].get('weight') is not None)
        trainers = sum(1 for m in matches if m['red_features'].get('trainer_recent_win_rate') is not None and m['blue_features'].get('trainer_recent_win_rate') is not None)
        print(json.dumps({'SELF_TEST': 'PASS' if len(matches) >= 8 and rich >= 6 else 'FAIL', 'meta': meta, 'matches': len(matches), 'age_pairs': rich, 'weight_pairs': weights, 'trainer_pairs': trainers}, ensure_ascii=False))
        if len(matches) < 8 or rich < 6:
            raise SystemExit(2)
        return

    payload = json.loads(DATA.read_text(encoding='utf-8'))
    source_url = BASE
    raw = fetch(source_url)
    linked, parsed, meta = enrich_payload(payload, raw, source_url)
    DATA.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({'BULL_FEATURES': 'PASS', 'linked': linked, 'parsed': parsed, 'card': meta}, ensure_ascii=False))


if __name__ == '__main__':
    main()
