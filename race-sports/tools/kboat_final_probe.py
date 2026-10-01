import re, urllib.request, html, socket

URLS=[
 'https://kboat.or.kr/race/dividendrate/final',
 'https://www.kboat.or.kr/race/dividendrate/final',
]
UA='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'

def get(url, timeout=12):
    req=urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language':'ko-KR,ko;q=0.9,en;q=0.7',
        'Connection':'close',
        'Cache-Control':'no-cache',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.geturl(), r.read().decode('utf-8','ignore')

for u in URLS:
    try:
        status, final, raw=get(u)
        print('FETCH',u,'STATUS',status,'FINAL',final,'LEN',len(raw))
        txt=html.unescape(re.sub(r'<[^>]+>',' ',raw))
        print('HAS_SINGLE', '단승식' in txt, 'HAS_ERROR', '예상치 못한 오류' in txt)
        for pat in ['raceNo','raceNum','race_no','searchRace','raceIndex','raceSeq','raceCnt','tms','raceNoSelect','dividendrate/final']:
            hits=[]
            for m in re.finditer(pat, raw, re.I):
                hits.append(raw[max(0,m.start()-240):m.start()+520].replace('\n',' ')[:760])
                if len(hits)>=3: break
            if hits:
                print('PATTERN',pat)
                for h in hits: print('SNIP',repr(h))
        print('FORMS', [x[:1200].replace('\n',' ') for x in re.findall(r'<form[\s\S]*?</form>',raw,re.I)[:2]])
        print('SELECTS', [x[:900].replace('\n',' ') for x in re.findall(r'<select[\s\S]*?</select>',raw,re.I)[:8]])
        controls=[]
        for m in re.finditer(r'경정\s*17',txt):
            pos=max(0,m.start()-500)
            controls.append(txt[pos:m.start()+500])
        print('TEXT17',repr(controls[:2]))
    except Exception as e:
        print('FETCH_ERROR',u,repr(e))
