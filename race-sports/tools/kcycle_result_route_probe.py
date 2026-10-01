import html
import re
import urllib.request

URL = 'https://www.kcycle.or.kr/race/result/general'
UA = 'Mozilla/5.0 (RACE SPORTS ANALYTICS KCYCLE historical route probe)'

req = urllib.request.Request(URL, headers={
    'User-Agent': UA,
    'Accept-Language': 'ko-KR,ko;q=.9,en;q=.7',
    'Cache-Control': 'no-cache',
})
with urllib.request.urlopen(req, timeout=15) as r:
    raw = r.read().decode('utf-8', 'ignore')

print('KCYCLE_RESULT_ROUTE_PROBE=START')
print('BYTES=', len(raw))

for tag in re.findall(r'<form\b[^>]*>', raw, flags=re.I):
    t = html.unescape(tag)
    if 'result' in t.lower() or 'search' in t.lower() or 'race' in t.lower():
        print('FORM=', t[:1000])

for tag in re.findall(r'<select\b[^>]*>', raw, flags=re.I):
    print('SELECT=', html.unescape(tag)[:1000])

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

for m in re.finditer(r'([A-Za-z][A-Za-z0-9_]{2,40})\s*[:=]\s*["\']?[^,;\n<]{0,80}', raw):
    s = m.group(0)
    if any(x in s.lower() for x in ('year','tms','day','result','race')):
        print('SCRIPT_HINT=', html.unescape(s)[:500])

print('KCYCLE_RESULT_ROUTE_PROBE=PASS')
