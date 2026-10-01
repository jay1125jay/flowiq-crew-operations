import re, urllib.request, html

URLS=[
 ('KBOAT_FINAL','https://kboat.or.kr/race/dividendrate/final'),
 ('KBOAT_FINAL_WWW','https://www.kboat.or.kr/race/dividendrate/final'),
 ('SPEEDON','https://speedon.or.kr/'),
 ('SPEEDON_WWW','https://www.speedon.or.kr/'),
]
UA='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'

def get(url, timeout=12):
    req=urllib.request.Request(url, headers={
        'User-Agent':UA,
        'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language':'ko-KR,ko;q=.9,en;q=.7',
        'Connection':'close','Cache-Control':'no-cache'
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.geturl(), r.read().decode('utf-8','ignore')

for tag,u in URLS:
    try:
        status,final,raw=get(u)
        txt=html.unescape(re.sub(r'<[^>]+>',' ',raw))
        print('FETCH',tag,'STATUS',status,'FINAL',final,'LEN',len(raw),'SINGLE',('단승' in txt),'ODDS',('배당' in txt))
        scripts=re.findall(r'<script[^>]+src=["\']([^"\']+)',raw,re.I)
        print('SCRIPTS',tag,scripts[-40:])
        for pat in ['배당','odds','dividend','raceNo','raceNum','raceSeq','boat','kboat','api/','axios','fetch(','ajax','XMLHttpRequest']:
            hits=[]
            for m in re.finditer(re.escape(pat),raw,re.I):
                hits.append(raw[max(0,m.start()-220):m.start()+560].replace('\n',' ')[:780])
                if len(hits)>=4:break
            if hits:
                print('PATTERN',tag,pat)
                for h in hits:print('SNIP',repr(h))
    except Exception as e:
        print('FETCH_ERROR',tag,u,repr(e))
