import re, urllib.request

UA='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'
BASE='https://kboat.or.kr'
URLS=[
 ('COMMON_FN',BASE+'/static/js/common-fn.js'),
 ('COMMON_RACE',BASE+'/static/js/common-race.js'),
 ('FINAL',BASE+'/race/dividendrate/final'),
]

def get(url, timeout=15):
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'*/*','Accept-Language':'ko-KR,ko;q=.9,en;q=.7','Connection':'close','Cache-Control':'no-cache'})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return r.read().decode('utf-8','ignore')

for tag,u in URLS:
    try:
        raw=get(u)
        print('FETCH',tag,'LEN',len(raw))
        for pat in ['fnGetUrl','BASE_URL','fnSearchRace','search.race','raceNo','stndYear','dayOrd','tms']:
            hits=[]
            for m in re.finditer(re.escape(pat),raw,re.I):
                hits.append(raw[max(0,m.start()-500):m.start()+1200].replace('\r','').replace('\n',' ')[:1700])
                if len(hits)>=5:break
            if hits:
                print('PATTERN',tag,pat)
                for h in hits:print('SNIP',repr(h))
        if tag=='FINAL':
            # print selected race controls and the first compact odds-table neighborhood
            for needle in ['fnSearchRace(', '단승식', '17경주']:
                p=raw.find(needle)
                print('FINAL_NEEDLE',needle,'POS',p,'SNIP',repr(raw[max(0,p-800):p+2200].replace('\r','').replace('\n',' ') if p>=0 else ''))
    except Exception as e:
        print('FETCH_ERROR',tag,repr(e))
