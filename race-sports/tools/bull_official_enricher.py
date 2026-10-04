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


def fetch(url, timeout=10, retries=2):
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
                time.sleep(1.0 * (i + 1))
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
    return re.sub(r'\n{2,}', '\n', s)


def event_meta(e):
    m = re.match(r'BULL-(\d{8})-(\d+)-(\d+)-(\d+)$', str(e.get('id') or ''))
    if not m:
        return None
    ymd, rnd, day, race = m.groups()
    return {'year':int(ymd[:4]),'date':f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}','round':int(rnd),'day':int(day),'race':int(race)}


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
    return {'year':int(m.group(1)),'round':int(m.group(2)),'day':int(m.group(3)),'date':f'{m.group(1)}-{m.group(4)}-{m.group(5)}'}


def parse_final_single(raw):
    text = textify(raw)
    hm = header_meta(text)
    sec = text
    idx = sec.find('단승식 배당률')
    if idx >= 0:
        sec = sec[idx:idx + 2500]
    m = re.search(r'(?:구분\s*)?홍\s+청\s+무\s+배당률\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)', sec)
    if not m:
        m = re.search(r'단승식[\s\S]{0,1200}?홍[\s\S]{0,80}?청[\s\S]{0,80}?무[\s\S]{0,500}?(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)', sec)
    odds = None if not m else {'RED':float(m.group(1)),'BLUE':float(m.group(2)),'DRAW':float(m.group(3))}
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
        red = re.search(r'홍\s+([^\s\n]+)\s+\[(승|패|무)\]', text)
        blue = re.search(r'청\s+([^\s\n]+)\s+\[(승|패|무)\]', text)
    if not red or not blue:
        return hm, None
    if red.group(2) == '승': winner = 'RED'
    elif blue.group(2) == '승': winner = 'BLUE'
    elif red.group(2) == '무' or blue.group(2) == '무': winner = 'DRAW'
    else: return hm, None
    markets = []
    for market, win, odds in re.findall(r'(단승|시단승|복승|시복승)\s+([^\n]+?)\s+(\d+(?:\.\d+)?)\s*(?:\n|$)', text):
        markets.append({'market':market,'winner':re.sub(r'\s+',' ',win).strip(),'odds':float(odds)})
    return hm, {
        'official':True,'status':'CONFIRMED',
        'winner':{'key':winner,'label':{'RED':'홍','DRAW':'무','BLUE':'청'}[winner],'name':red.group(1) if winner=='RED' else blue.group(1) if winner=='BLUE' else '무승부'},
        'sides':{'RED':{'name':red.group(1),'decision':red.group(2)},'BLUE':{'name':blue.group(1),'decision':blue.group(2)}},
        'markets':markets,'source':'CPC_RESULT_OFFICIAL',
    }


def set_provider(payload, name, status, detail):
    payload['providers'] = [p for p in payload.get('providers', []) if p.get('provider') != name]
    payload['providers'].append({'provider':name,'status':status,'detail':detail})


def apply_odds(e, odds, observed_at, source_url, capture_mode=None):
    if not odds: return False
    try:
        if not all(float(odds.get(k) or 0) > 0 for k in ('RED','DRAW','BLUE')):
            return False
    except Exception:
        return False
    om = {o.get('key'):o for o in e.get('outcomes',[])}
    if not all(k in om for k in ('RED','DRAW','BLUE')): return False
    if capture_mode not in (None, 'PRE_RACE_OFFICIAL', 'LATE_OFFICIAL_RECOVERY'):
        return False
    pre = e.get('status') == 'SCHEDULED' and not e.get('result')
    mode = capture_mode or ('PRE_RACE_OFFICIAL' if pre else 'LATE_OFFICIAL_RECOVERY')
    snap = {'RED':odds['RED'],'DRAW':odds['DRAW'],'BLUE':odds['BLUE']}
    hist = list(e.get('odds_history') or [])
    prev = hist[-1].get('odds',{}) if hist else {}
    if prev != snap:
        hist.append({'observed_at':observed_at,'market':'단승식','source':'CPC_FINAL_SINGLE_AUTO','capture_mode':mode,'odds':snap,'source_url':source_url})
        e['odds_history'] = hist[-120:]
    for key in ('RED','DRAW','BLUE'):
        om[key]['odds'] = float(odds[key]); om[key]['odds_source'] = 'CPC_FINAL_SINGLE_AUTO'; om[key]['odds_capture_mode'] = mode; om[key]['odds_observed_at'] = observed_at
    return True


def apply_result(e, result, observed_at, source_url):
    if not result: return False
    result['updated_at'] = observed_at; result['source_url'] = source_url
    e['result'] = result; e['status'] = 'FINAL'
    winner = result.get('winner',{}).get('key')
    for o in e.get('outcomes',[]): o['won'] = bool(winner and o.get('key') == winner)
    return True


def delta_minutes(e, z):
    try:
        hh, mm = map(int, str(e.get('start_time')).split(':'))
        return hh*60 + mm - (z.hour*60 + z.minute)
    except Exception:
        return 9999

def rolling_start(e):
    s=str(e.get('start_text_official') or '')+' '+str(e.get('start_label') or '')+' '+str(e.get('start_time') or '')
    return '발매 마감 후' in s or '순차 진행' in s


def has_official_odds(e):
    om = {o.get('key'):o for o in e.get('outcomes',[]) if o.get('key')}
    try:
        return all(
            k in om and
            om[k].get('odds_source') == 'CPC_FINAL_SINGLE_AUTO' and
            float(om[k].get('odds') or 0) > 0
            for k in ('RED','DRAW','BLUE')
        )
    except Exception:
        return False


def capture_mode_for(e):
    return 'LATE_OFFICIAL_RECOVERY' if e.get('result') or e.get('status') == 'FINAL' else 'PRE_RACE_OFFICIAL'


def parse_ts(v):
    try:
        return datetime.fromisoformat(str(v).replace('Z','+00:00'))
    except Exception:
        return None


def repair_capture_modes(e):
    result_at = parse_ts((e.get('result') or {}).get('updated_at'))
    if not result_at:
        return 0
    changed = 0
    for o in e.get('outcomes',[]):
        if o.get('odds_source') != 'CPC_FINAL_SINGLE_AUTO' or o.get('odds_capture_mode') != 'PRE_RACE_OFFICIAL':
            continue
        odds_at = parse_ts(o.get('odds_observed_at'))
        if odds_at and odds_at >= result_at:
            o['odds_capture_mode'] = 'LATE_OFFICIAL_RECOVERY'
            changed += 1
    for h in e.get('odds_history',[]) or []:
        if h.get('source') != 'CPC_FINAL_SINGLE_AUTO' or h.get('capture_mode') != 'PRE_RACE_OFFICIAL':
            continue
        odds_at = parse_ts(h.get('observed_at'))
        if odds_at and odds_at >= result_at:
            h['capture_mode'] = 'LATE_OFFICIAL_RECOVERY'
            changed += 1
    return changed


def self_test():
    odds_meta = {'year':2026,'round':33,'day':2,'race':11}
    result_meta = {'year':2026,'round':19,'day':2,'race':2}
    oh, odds, red, blue = parse_final_single(fetch(url_for(ODDS_BASE, odds_meta)))
    rh, result = parse_result(fetch(url_for(RESULT_BASE, result_meta)))
    assert rolling_start({'start_text_official':'02경기 발매 마감 후','start_time':'순차 진행'})
    ok = bool(oh and oh['year']==2026 and oh['round']==33 and oh['day']==2 and odds and all(odds.get(k,0)>0 for k in ('RED','DRAW','BLUE')) and rh and rh['year']==2026 and rh['round']==19 and rh['day']==2 and result and result.get('winner',{}).get('key') in ('RED','DRAW','BLUE'))
    print(json.dumps({'SELF_TEST':'PASS' if ok else 'FAIL','odds_header':oh,'odds':odds,'odds_bulls':[red,blue],'result_header':rh,'winner':(result or {}).get('winner')},ensure_ascii=False))
    if not ok: raise SystemExit(2)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--self-test',action='store_true'); args = ap.parse_args()
    if args.self_test: self_test(); return
    payload = json.loads(DATA.read_text(encoding='utf-8'))
    z = datetime.now(KST); observed_at = z.isoformat()
    bull = sorted(
        [e for e in payload.get('events',[]) if e.get('sport')=='BULL'],
        key=lambda x:int(x.get('race_no') or 999)
    )
    odds_linked = results_linked = odds_checked = results_checked = 0
    odds_errors=[]; result_errors=[]
    capture_repairs = sum(repair_capture_modes(e) for e in bull)

    # Resolve official results first. For CPC rolling races (2+), poll in order
    # and stop at the first race that is not yet officially confirmed.
    fixed_results = [
        e for e in bull
        if not rolling_start(e)
        and not e.get('result')
        and e.get('status') in ('LIVE','RESULT_PENDING','FINAL')
    ]
    rolling_results = [
        e for e in bull
        if rolling_start(e) and not e.get('result') and e.get('status') != 'FINAL'
    ]
    result_targets = fixed_results + rolling_results

    for e in result_targets:
        m=event_meta(e)
        if not m: continue
        results_checked += 1
        is_rolling=rolling_start(e)
        try:
            ru=url_for(RESULT_BASE,m); rh,result=parse_result(fetch(ru,timeout=8,retries=1))
            confirmed=bool(rh and rh['date']==m['date'] and rh['round']==m['round'] and rh['day']==m['day'] and result)
            if confirmed and apply_result(e,result,observed_at,ru):
                results_linked += 1
            elif is_rolling:
                break
        except Exception as x:
            result_errors.append(f"{e.get('id')}:{type(x).__name__}:{x}"[:220])
            if is_rolling: break

    # Recover missing official final odds for already-finished races, and poll
    # only the first unresolved rolling race for a genuine pre-race capture.
    fixed_current = [
        e for e in bull
        if not rolling_start(e)
        and not has_official_odds(e)
        and e.get('status') == 'SCHEDULED'
        and -10 <= delta_minutes(e,z) <= 75
    ]
    fixed_recovery = [
        e for e in bull
        if not rolling_start(e) and e.get('result') and not has_official_odds(e)
    ]
    rolling_recovery = [
        e for e in bull
        if rolling_start(e) and e.get('result') and not has_official_odds(e)
    ]
    rolling_pending = [
        e for e in bull
        if rolling_start(e) and not e.get('result') and not has_official_odds(e)
    ]
    raw_odds_targets = fixed_current + fixed_recovery + rolling_recovery + (rolling_pending[:1] if rolling_pending else [])
    odds_targets=[]; seen=set()
    for e in raw_odds_targets:
        eid=e.get('id')
        if not eid or eid in seen: continue
        seen.add(eid); odds_targets.append(e)

    for e in odds_targets:
        m=event_meta(e)
        if not m: continue
        odds_checked += 1
        try:
            ou=url_for(ODDS_BASE,m); oh,odds,red,blue=parse_final_single(fetch(ou,timeout=8,retries=1))
            if oh and oh['date']==m['date'] and oh['round']==m['round'] and oh['day']==m['day']:
                same=True
                if red and e.get('left'): same = same and re.sub(r'\s+','',red)==re.sub(r'\s+','',str(e.get('left')))
                if blue and e.get('right'): same = same and re.sub(r'\s+','',blue)==re.sub(r'\s+','',str(e.get('right')))
                mode=capture_mode_for(e)
                if same and apply_odds(e,odds,observed_at,ou,capture_mode=mode):
                    odds_linked += 1
        except Exception as x:
            odds_errors.append(f"{e.get('id')}:{type(x).__name__}:{x}"[:220])

    odds_present = sum(1 for e in bull if has_official_odds(e))
    final_present = sum(1 for e in bull if e.get('result') and e.get('status')=='FINAL')
    pre_present = sum(
        1 for e in bull if has_official_odds(e)
        and all(o.get('odds_capture_mode')=='PRE_RACE_OFFICIAL' for o in e.get('outcomes',[]))
    )
    late_present = sum(
        1 for e in bull if has_official_odds(e)
        and any(o.get('odds_capture_mode')=='LATE_OFFICIAL_RECOVERY' for o in e.get('outcomes',[]))
    )
    odds_status = 'NO_TODAY_CARD' if not bull else ('PASS' if odds_present==len(bull) else ('PARTIAL' if odds_present else 'WAITING'))
    result_status = 'NO_TODAY_CARD' if not bull else ('PASS' if final_present==len(bull) else ('PARTIAL' if final_present else 'WAITING'))

    set_provider(payload,'BULL_LIVE_ODDS_CPC',odds_status,{
        'market':'단승식',
        'capture':'official final odds after sales close',
        'checked':odds_checked,
        'linked_this_run':odds_linked,
        'coverage':{'official_odds_events':odds_present,'total_events':len(bull),'pre_race':pre_present,'late_recovery':late_present},
        'capture_mode_repairs':capture_repairs,
        'errors':odds_errors[-5:],
        'source':ODDS_BASE
    })
    set_provider(payload,'BULL_RESULT_CPC',result_status,{
        'checked':results_checked,
        'confirmed_this_run':results_linked,
        'coverage':{'final_events':final_present,'total_events':len(bull)},
        'errors':result_errors[-5:],
        'source':RESULT_BASE
    })
    DATA.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps({'BULL_OFFICIAL_ENRICH':'PASS','events':len(bull),'odds_checked':odds_checked,'odds_linked':odds_linked,'odds_present':odds_present,'results_checked':results_checked,'results_linked':results_linked,'final_present':final_present,'capture_mode_repairs':capture_repairs,'odds_errors':len(odds_errors),'result_errors':len(result_errors)},ensure_ascii=False))


if __name__ == '__main__': main()
