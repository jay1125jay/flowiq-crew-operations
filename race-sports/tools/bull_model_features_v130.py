from __future__ import annotations

import argparse
import html
import json
import math
import re
import time
import urllib.request
from datetime import timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path

KST = timezone(timedelta(hours=9))
DATA = Path('race-sports/data/today.json')
UA = 'Mozilla/5.0 (RACE SPORTS ANALYTICS GitHub official-readonly)'
BASE = 'https://www.cpc.or.kr/cpc/module/game/gameCard/confirmed/index.do?menu_idx=52'

NUM_FEATURES = [
    'red_age','blue_age','age_diff',
    'red_weight','blue_weight','weight_diff',
    'red_card_win_pct','blue_card_win_pct','card_win_pct_diff',
    'red_record_wins','blue_record_wins','red_record_draws','blue_record_draws','red_record_losses','blue_record_losses',
    'red_recent_wins','blue_recent_wins','red_recent_draws','blue_recent_draws','red_recent_losses','blue_recent_losses',
    'red_h2h_wins','blue_h2h_wins','red_h2h_meets','blue_h2h_meets','red_h2h_rate','blue_h2h_rate',
    'red_trainer_wins','blue_trainer_wins','red_trainer_starts','blue_trainer_starts','red_trainer_rate','blue_trainer_rate',
    'red_joint_wins','blue_joint_wins','red_joint_draws','blue_joint_draws','red_joint_losses','blue_joint_losses',
    'red_prior_games','blue_prior_games','prior_games_diff',
    'red_prior_win_rate','blue_prior_win_rate','prior_win_rate_diff',
    'red_prior_draw_rate','blue_prior_draw_rate','prior_draw_rate_diff',
    'weight_class_ord','start_minutes',
]
CAT_FEATURES = [
    'red_breed','blue_breed','red_horn','blue_horn','red_skill','blue_skill',
    'red_region','blue_region','red_trainer','blue_trainer',
    'red_current_class','blue_current_class','red_previous_class','blue_previous_class',
]


def clean(v):
    return re.sub(r'\s+', ' ', html.unescape(str(v or ''))).strip()


def norm(v):
    return re.sub(r'\s+', '', str(v or '')).strip()


def num(v):
    try:
        if v in (None, ''):
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


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


class TP(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.depth = 0
        self.table = None
        self.row = None
        self.cell = None
        self.in_cell = False
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == 'table':
            self.depth += 1
            if self.depth == 1:
                self.table = []
        elif self.depth == 1 and tag == 'tr':
            self.row = []
        elif self.depth == 1 and tag in ('td', 'th'):
            self.cell = []
            self.in_cell = True
        if tag in ('br','p','div','h1','h2','h3','h4','li'):
            self.text_parts.append('\n')

    def handle_data(self, data):
        if self.in_cell and self.cell is not None:
            self.cell.append(data)
        self.text_parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.depth == 1 and tag in ('td', 'th'):
            if self.row is not None:
                self.row.append(clean(' '.join(self.cell or [])))
            self.cell = None
            self.in_cell = False
        elif self.depth == 1 and tag == 'tr':
            if self.table is not None and self.row is not None:
                self.table.append(self.row)
            self.row = None
        elif tag == 'table':
            if self.depth == 1 and self.table is not None:
                self.tables.append(self.table)
                self.table = None
            self.depth = max(0, self.depth - 1)
        if tag in ('p','div','h1','h2','h3','h4','li','tr'):
            self.text_parts.append('\n')

    def text(self):
        s = html.unescape(''.join(self.text_parts)).replace('\r', '')
        s = re.sub(r'[ \t]+', ' ', s)
        s = re.sub(r'\n[ \t]+', '\n', s)
        return re.sub(r'\n{2,}', '\n', s)


def drows(t):
    return [r for r in t if r and clean(r[0]) in ('홍', '청')]


def ttext(t):
    return ' '.join(clean(c) for r in t for c in r if clean(c))


def pct(v):
    m = re.search(r'(-?\d+(?:\.\d+)?)\s*%', clean(v))
    return float(m.group(1)) if m else None


def wdl(v):
    m = re.search(r'(\d+)\s*/\s*(\d+)\s*/\s*(\d+)', clean(v))
    return tuple(float(m.group(i)) for i in (1,2,3)) if m else (None, None, None)


def pair(v):
    m = re.fullmatch(r'\s*(\d+)\s*/\s*(\d+)\s*', clean(v))
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def weight(v):
    m = re.search(r'(?<!\d)(\d{3,4})(?:\s*\(|\s*$)', clean(v).replace(',', ''))
    if not m:
        return None
    x = float(m.group(1))
    return x if 300 <= x <= 1500 else None


def core(r):
    v = r + [''] * max(0, 17 - len(r))
    W,D,L = wdl(v[10] if len(v) > 10 else '')
    return {
        'color': clean(v[0]),
        'name': clean(v[1]),
        'age': num(v[2]),
        'breed': clean(v[3]),
        'horn': clean(v[4]),
        'skill': clean(v[5]),
        'owner': clean(v[6]),
        'region': clean(v[7]),
        'trainer': clean(v[8]),
        'card_win_rate_pct': pct(v[9]),
        'record_wins': W,
        'record_draws': D,
        'record_losses': L,
    }


def recent(r):
    txt = ' | '.join(r)
    w = None
    for c in reversed(r):
        x = weight(c)
        if x is not None:
            w = x
            break
    classes = [clean(c) for c in r if clean(c) in ('갑','을','병')]
    return {
        'name': clean(r[1]) if len(r) > 1 else '',
        'recent_wins': float(len(re.findall(r'\[\s*승\s*\]', txt))),
        'recent_draws': float(len(re.findall(r'\[\s*무\s*\]', txt))),
        'recent_losses': float(len(re.findall(r'\[\s*패\s*\]', txt))),
        'weight': w,
        'current_class': classes[-2] if len(classes) >= 2 else (classes[-1] if classes else ''),
        'previous_class': classes[-1] if len(classes) >= 2 else '',
    }


def h2h(r, trainer):
    ps = []
    tri = None
    for i, c in enumerate(r[2:], 2):
        p = pair(c)
        if p[0] is not None:
            ps.append((i, p))
        t = wdl(c)
        if t[0] is not None:
            tri = t
    hw = hm = tw = ts = None
    if ps:
        hw, hm = ps[0][1]
    ti = None
    for i, c in enumerate(r):
        if clean(c) == clean(trainer) and clean(trainer):
            ti = i
            break
    if ti is not None:
        for i, p in ps:
            if i > ti:
                tw, ts = p
                break
    elif len(ps) >= 2:
        tw, ts = ps[1][1]
    if tri is None:
        tri = (None, None, None)
    return {
        'name': clean(r[1]) if len(r) > 1 else '',
        'h2h_wins': hw,
        'h2h_meets': hm,
        'trainer_wins': tw,
        'trainer_starts': ts,
        'joint_wins': tri[0],
        'joint_draws': tri[1],
        'joint_losses': tri[2],
    }


def class_ord(v):
    return {'병':0.0,'을':1.0,'갑':2.0}.get(clean(v))


def start_minutes(v):
    s = clean(v)
    m = re.search(r'(\d{1,2})\s*시\s*(\d{1,2})\s*분', s)
    if not m:
        m = re.search(r'(\d{1,2}):(\d{2})', s)
    return float(int(m.group(1))*60 + int(m.group(2))) if m else None


def div(a, b, default=None):
    a, b = num(a), num(b)
    if a is None or b in (None, 0):
        return default
    return a / b


def diff(a, b):
    a, b = num(a), num(b)
    return a - b if a is not None and b is not None else None


def prior_proxy(side):
    w = num(side.get('record_wins')) or 0.0
    d = num(side.get('record_draws')) or 0.0
    l = num(side.get('record_losses')) or 0.0
    g = w + d + l
    return g, (w/g if g else 0.5), (d/g if g else 0.0)


def flat_features(red, blue, grade, start_text):
    rg, rwr, rdr = prior_proxy(red)
    bg, bwr, bdr = prior_proxy(blue)
    out = {
        'red_age': num(red.get('age')), 'blue_age': num(blue.get('age')), 'age_diff': diff(red.get('age'), blue.get('age')),
        'red_weight': num(red.get('weight')), 'blue_weight': num(blue.get('weight')), 'weight_diff': diff(red.get('weight'), blue.get('weight')),
        'red_card_win_pct': num(red.get('card_win_rate_pct')), 'blue_card_win_pct': num(blue.get('card_win_rate_pct')), 'card_win_pct_diff': diff(red.get('card_win_rate_pct'), blue.get('card_win_rate_pct')),
        'red_record_wins': num(red.get('record_wins')), 'blue_record_wins': num(blue.get('record_wins')),
        'red_record_draws': num(red.get('record_draws')), 'blue_record_draws': num(blue.get('record_draws')),
        'red_record_losses': num(red.get('record_losses')), 'blue_record_losses': num(blue.get('record_losses')),
        'red_recent_wins': num(red.get('recent_wins')), 'blue_recent_wins': num(blue.get('recent_wins')),
        'red_recent_draws': num(red.get('recent_draws')), 'blue_recent_draws': num(blue.get('recent_draws')),
        'red_recent_losses': num(red.get('recent_losses')), 'blue_recent_losses': num(blue.get('recent_losses')),
        'red_h2h_wins': num(red.get('h2h_wins')), 'blue_h2h_wins': num(blue.get('h2h_wins')),
        'red_h2h_meets': num(red.get('h2h_meets')), 'blue_h2h_meets': num(blue.get('h2h_meets')),
        'red_h2h_rate': div(red.get('h2h_wins'), red.get('h2h_meets'), 0.5), 'blue_h2h_rate': div(blue.get('h2h_wins'), blue.get('h2h_meets'), 0.5),
        'red_trainer_wins': num(red.get('trainer_wins')), 'blue_trainer_wins': num(blue.get('trainer_wins')),
        'red_trainer_starts': num(red.get('trainer_starts')), 'blue_trainer_starts': num(blue.get('trainer_starts')),
        'red_trainer_rate': div(red.get('trainer_wins'), red.get('trainer_starts'), 0.5), 'blue_trainer_rate': div(blue.get('trainer_wins'), blue.get('trainer_starts'), 0.5),
        'red_joint_wins': num(red.get('joint_wins')), 'blue_joint_wins': num(blue.get('joint_wins')),
        'red_joint_draws': num(red.get('joint_draws')), 'blue_joint_draws': num(blue.get('joint_draws')),
        'red_joint_losses': num(red.get('joint_losses')), 'blue_joint_losses': num(blue.get('joint_losses')),
        'red_prior_games': rg, 'blue_prior_games': bg, 'prior_games_diff': rg-bg,
        'red_prior_win_rate': rwr, 'blue_prior_win_rate': bwr, 'prior_win_rate_diff': rwr-bwr,
        'red_prior_draw_rate': rdr, 'blue_prior_draw_rate': bdr, 'prior_draw_rate_diff': rdr-bdr,
        'weight_class_ord': class_ord(grade), 'start_minutes': start_minutes(start_text),
        'red_breed': clean(red.get('breed')), 'blue_breed': clean(blue.get('breed')),
        'red_horn': clean(red.get('horn')), 'blue_horn': clean(blue.get('horn')),
        'red_skill': clean(red.get('skill')), 'blue_skill': clean(blue.get('skill')),
        'red_region': clean(red.get('region')), 'blue_region': clean(blue.get('region')),
        'red_trainer': clean(red.get('trainer')), 'blue_trainer': clean(blue.get('trainer')),
        'red_current_class': clean(red.get('current_class')), 'blue_current_class': clean(blue.get('current_class')),
        'red_previous_class': clean(red.get('previous_class')), 'blue_previous_class': clean(blue.get('previous_class')),
    }
    return out


def parse_card(raw):
    tp = TP(); tp.feed(raw); text = tp.text()
    hdr = re.search(r'(\d{4})년도\s*(\d+)회차\s*(\d+)일차\s*\((\d{2})월\s*(\d{2})일\)표', text)
    meta = None
    if hdr:
        meta = {'year':int(hdr.group(1)),'round':int(hdr.group(2)),'day':int(hdr.group(3)),'date':f'{hdr.group(1)}-{hdr.group(4)}-{hdr.group(5)}'}
    headers = [
        {'race_no':int(m.group(1)),'grade':m.group(2),'start_text':m.group(3)}
        for m in re.finditer(r'(\d{2})경기\s*([갑을병])?\s*\(시작시간:\s*([^)]+)\)', text)
    ]
    races = []
    current = None
    core_index = 0
    for t in tp.tables:
        txt = ttext(t); rows = drows(t)
        if len(rows) < 2:
            continue
        bc = {clean(r[0]):r for r in rows if clean(r[0]) in ('홍','청')}
        if '홍' not in bc or '청' not in bc:
            continue
        if all(x in txt for x in ('나이','품종','뿔모양','승률')):
            h = headers[core_index] if core_index < len(headers) else {'race_no':core_index+1,'grade':None,'start_text':''}
            core_index += 1
            current = {'race_no':h['race_no'],'grade':h['grade'],'start_text':h['start_text'],'red':core(bc['홍']),'blue':core(bc['청'])}
            races.append(current)
        elif current is not None and ('최근' in txt and '체중' in txt and '체급' in txt):
            rr, bb = recent(bc['홍']), recent(bc['청'])
            if norm(rr['name']) == norm(current['red']['name']): current['red'].update(rr)
            if norm(bb['name']) == norm(current['blue']['name']): current['blue'].update(bb)
        elif current is not None and ('상대전적' in txt and '조교사' in txt):
            rr, bb = h2h(bc['홍'], current['red'].get('trainer','')), h2h(bc['청'], current['blue'].get('trainer',''))
            if norm(rr['name']) == norm(current['red']['name']): current['red'].update(rr)
            if norm(bb['name']) == norm(current['blue']['name']): current['blue'].update(bb)
    for r in races:
        r['features'] = flat_features(r['red'], r['blue'], r['grade'], r['start_text'])
    return meta, races


def set_provider(payload, name, status, detail):
    payload['providers'] = [p for p in payload.get('providers', []) if p.get('provider') != name]
    payload['providers'].append({'provider':name,'status':status,'detail':detail})


def enrich(payload, raw, source_url):
    meta, races = parse_card(raw)
    by_no = {r['race_no']:r for r in races}
    linked = 0
    for e in payload.get('events', []):
        if e.get('sport') != 'BULL':
            continue
        r = by_no.get(int(e.get('race_no') or 0))
        if not r:
            continue
        if e.get('left') and norm(e.get('left')) != norm(r['red'].get('name')):
            continue
        if e.get('right') and norm(e.get('right')) != norm(r['blue'].get('name')):
            continue
        e['bull_features'] = {'RED':r['red'],'BLUE':r['blue'],'pair':{'grade':r['grade'],'start_text':r['start_text']}}
        e['bull_model_features'] = r['features']
        e['bull_feature_source'] = 'CPC_CONFIRMED_CARD_OFFICIAL_V130_ADAPTER'
        linked += 1
    set_provider(payload,'BULL_MODEL_FEATURES_CPC','PASS' if linked else ('NO_TODAY_CARD' if not any(e.get('sport')=='BULL' for e in payload.get('events',[])) else 'UNLINKED'),{
        'linked':linked,'parsed_matches':len(races),'card':meta,'numeric_features':len(NUM_FEATURES),'categorical_features':len(CAT_FEATURES),'source_url':source_url,
        'prior_feature_note':'career-card W/D/L is used as current scoring proxy for prior-history state; validated training artifact remains unchanged',
    })
    return linked, meta, races


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--self-test-url'); args = ap.parse_args()
    raw = fetch(args.self_test_url or BASE)
    if args.self_test_url:
        meta, races = parse_card(raw)
        complete = sum(1 for r in races if sum(1 for f in NUM_FEATURES if r['features'].get(f) is not None) >= 35)
        ok = len(races) >= 8 and complete >= 6
        print(json.dumps({'SELF_TEST':'PASS' if ok else 'FAIL','meta':meta,'matches':len(races),'feature_rich':complete,'num_features':len(NUM_FEATURES),'cat_features':len(CAT_FEATURES)},ensure_ascii=False))
        if not ok: raise SystemExit(2)
        return
    payload = json.loads(DATA.read_text(encoding='utf-8'))
    linked, meta, races = enrich(payload, raw, BASE)
    DATA.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps({'BULL_MODEL_FEATURES':'PASS','linked':linked,'parsed':len(races),'card':meta},ensure_ascii=False))


if __name__ == '__main__':
    main()
