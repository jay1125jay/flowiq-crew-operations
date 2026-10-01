import html
import re
import time
import urllib.parse
import urllib.request

URL = 'https://www.kcycle.or.kr/race/result/general'
UA = 'Mozilla/5.0 (RACE SPORTS ANALYTICS KCYCLE historical route probe)'
TARGET = '2026-09-20'


def fetch(url, timeout=8, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA,
                'Accept-Language': 'ko-KR,ko;q=.9,en;q=.7',
                'Cache-Control': 'no-cache',
                'Connection': 'close',
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode('utf-8', 'ignore')
        except Exception as exc:
            last = exc
            if i + 1 < retries:
                time.sleep(1.0 + i)
    raise last


def page_date(raw):
    text = re.sub(r'<[^>]+>', ' ', raw)
    text = re.sub(r'\s+', ' ', html.unescape(text))
    for pat in [
        r'(\d{4})년\s*\d+회\s*\d+일차\s*\((\d{2})월\s*(\d{2})일\)\s*경주결과',
        r'(\d{4})[-./](\d{2})[-./](\d{2})',
    ]:
        m = re.search(pat, text)
        if m:
            return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    return None


print('KCYCLE_RESULT_ROUTE_PROBE=START')
try:
    raw = fetch(URL)
except Exception as exc:
    print('KCYCLE_RESULT_ROUTE_PROBE=UNAVAILABLE')
    print('ERROR=', type(exc).__name__, str(exc)[:250])
    raise SystemExit(0)

print('BYTES=', len(raw))
print('BASE_PAGE_DATE=', page_date(raw))

for tag in re.findall(r'<form\b[^>]*>', raw, flags=re.I):
    t = html.unescape(tag)
    if 'result' in t.lower() or 'search' in t.lower() or 'race' in t.lower():
        print('FORM=', t[:1000])

select_names = []
for tag in re.findall(r'<select\b[^>]*>', raw, flags=re.I):
    text = html.unescape(tag)
    print('SELECT=', text[:1000])
    m = re.search(r'\bname=["\']([^"\']+)', text, re.I)
    if m:
        select_names.append(m.group(1))

for m in re.finditer(r'<option\b([^>]*)>([\s\S]*?)</option>', raw, flags=re.I):
    attrs = html.unescape(m.group(1))
    label = re.sub(r'<[^>]+>', ' ', m.group(2))
    label = re.sub(r'\s+', ' ', html.unescape(label)).strip()
    if 'selected' in attrs.lower() or re.search(r'2026|09월|08월|38회|37회', label):
        print('OPTION=', attrs[:500], ' LABEL=', label[:300])

urls = []
for m in re.finditer(r'(?:href|action)=["\']([^"\']+)["\']', raw, flags=re.I):
    u = html.unescape(m.group(1))
    if 'result/general' in u or 'race/result' in u:
        urls.append(u)
for u in dict.fromkeys(urls):
    print('RESULT_URL_REF=', u)

for token in [
    'searchYear','searchTms','searchDay','searchDayOrd','searchStndYear',
    'stndYear','raceYear','raceTms','raceDay','meet','raceNo','searchDate',
    'selectYear','selectTms','selectDay','result/general'
]:
    if token.lower() in raw.lower():
        print('TOKEN_PRESENT=', token)

# If markup did not make the query contract obvious, probe a very small set of
# common GET contracts. We accept a route only when the rendered date exactly
# matches TARGET, so a false positive cannot be promoted into the collector.
candidates = [
    {'year':'2026','tms':'38','day':'3'},
    {'year':'2026','week':'38','day':'3'},
    {'searchYear':'2026','searchTms':'38','searchDay':'3'},
    {'searchStndYear':'2026','searchTms':'38','searchDayOrd':'3'},
    {'stndYear':'2026','tms':'38','dayOrd':'3'},
    {'raceYear':'2026','raceTms':'38','raceDay':'3'},
]
for params in candidates:
    url = URL + '?' + urllib.parse.urlencode(params)
    try:
        body = fetch(url, timeout=6, retries=1)
        rendered = page_date(body)
        print('QUERY_PROBE=', params, ' PAGE_DATE=', rendered)
        if rendered == TARGET:
            print('QUERY_MATCH=', params)
            break
    except Exception as exc:
        print('QUERY_PROBE_FAIL=', params, type(exc).__name__)

print('KCYCLE_RESULT_ROUTE_PROBE=PASS')
