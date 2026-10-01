import re,urllib.request
u='https://www.kboat.or.kr/'
r=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0 (RACE SPORTS ANALYTICS probe)','Accept-Language':'ko-KR,ko;q=.9'})
raw=urllib.request.urlopen(r,timeout=20).read().decode('utf-8','ignore')
print('LEN',len(raw))
for term in ['AI예측','ai','predict','prediction','prob','raceNo','racer']:
 print('TERM',term,'COUNT',len(re.findall(term,raw,re.I)))
for term in ['AI예측','raceNo','predict']:
 m=re.search(term,raw,re.I)
 if m: print('SNIP',term,repr(raw[max(0,m.start()-2000):m.start()+5000]))
