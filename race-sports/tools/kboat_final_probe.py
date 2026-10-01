import re, urllib.request, html
UA='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'
BASE='https://kboat.or.kr/race/dividendrate/final/2026/40/2'

def get(url,timeout=12):
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8','Accept-Language':'ko-KR,ko;q=.9,en;q=.7','Connection':'close','Cache-Control':'no-cache'})
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.read().decode('utf-8','ignore')

def textify(s):
    s=re.sub(r'<[^>]+>',' ',s);return re.sub(r'\s+',' ',html.unescape(s)).strip()

def odds(raw):
    h=re.search(r'<h3[^>]*>\s*단승식\s*</h3>',raw,re.I)
    if not h:return None
    sec=raw[h.end():h.end()+8000];tb=re.search(r'<tbody[^>]*>([\s\S]*?)</tbody>',sec,re.I)
    if not tb:return None
    vals=[]
    for c in re.findall(r'<td[^>]*>([\s\S]*?)</td>',tb.group(1),re.I):
        q=re.search(r'(?<!\d)(\d+(?:\.\d+)?)(?!\d)',textify(c).replace(',',''))
        if q:vals.append(float(q.group(1)))
        if len(vals)>=6:break
    return vals

for rn in (15,16,17):
    for form in (str(rn),f'{rn:02d}'):
        u=f'{BASE}/{form}'
        try:
            raw=get(u);print('RACE',rn,'FORM',form,'LEN',len(raw),'ERRORPAGE',('예상치 못한 오류' in textify(raw)),'ODDS',odds(raw))
            p=raw.find('<h3>단승식</h3>');print('SNIP',repr(raw[p:p+1800].replace('\n',' ') if p>=0 else 'NO_H3'))
        except Exception as e:print('RACE',rn,'FORM',form,'FETCH_ERROR',repr(e))
