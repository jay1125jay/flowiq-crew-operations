import json,re,html,urllib.request
from pathlib import Path

UA='Mozilla/5.0 (RACE SPORTS ANALYTICS official-readonly)'
DATA=Path('race-sports/data/today.json')
URL='https://www.kboat.or.kr/rankingpredict'

def fetch(url,timeout=20):
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept-Language':'ko-KR,ko;q=.9'})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return r.read().decode('utf-8','ignore')

def textify(s):
    s=re.sub(r'<script[\s\S]*?</script>',' ',s,flags=re.I)
    s=re.sub(r'<style[\s\S]*?</style>',' ',s,flags=re.I)
    s=re.sub(r'<br\s*/?\s*>','\n',s,flags=re.I)
    s=re.sub(r'</(tr|td|th|div|p|li|h1|h2|h3|h4|option)>','\n',s,flags=re.I)
    s=re.sub(r'<[^>]+>',' ',s)
    s=html.unescape(s).replace('\r','')
    s=re.sub(r'[ \t]+',' ',s)
    s=re.sub(r'\n[ \t]+','\n',s)
    s=re.sub(r'\n{2,}','\n',s)
    return s

def parse(raw):
    t=textify(raw)
    stamp=None
    m=re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*기준',t)
    if m: stamp=m.group(1)
    markers=list(re.finditer(r'(?:^|\n)(\d{2})R\s*(?=\n)',t))
    out={}
    for i,m in enumerate(markers):
        rn=int(m.group(1))
        seg=t[m.end():(markers[i+1].start() if i+1<len(markers) else len(t))]
        pairs=[]
        for p in re.finditer(r'(?:^|\n)\s*([1-6])\s*\n\s*(\d+(?:\.\d+)?)%\s*(?=\n)',seg):
            n=int(p.group(1)); v=float(p.group(2))/100.0
            if n not in [x[0] for x in pairs]: pairs.append((n,v))
            if len(pairs)>=6: break
        if len(pairs)==6:
            total=sum(v for _,v in pairs)
            if 0.98<=total<=1.02:
                out[rn]={f'N{n}':v for n,v in pairs}
    return out,stamp

def main():
    payload=json.loads(DATA.read_text(encoding='utf-8'))
    preds,stamp=parse(fetch(URL))
    linked=0
    for e in payload.get('events',[]):
        if e.get('sport')!='BOAT': continue
        p=preds.get(int(e.get('race_no') or 0),{})
        if not p: continue
        for o in e.get('outcomes',[]):
            if o.get('key') in p:
                o['model_p']=p[o['key']]
                o['model_source']='KBOAT_AI_OFFICIAL'
                o['model_updated_at']=stamp
                linked+=1
    providers=[x for x in payload.get('providers',[]) if x.get('provider')!='BOAT_AI_KBOAT']
    providers.append({'provider':'BOAT_AI_KBOAT','status':'PASS' if preds else 'FAIL','detail':{'races':len(preds),'linked_outcomes':linked,'updated_at':stamp,'source_url':URL,'meaning':'official AI win probability'}})
    payload['providers']=providers
    DATA.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps({'ai_races':len(preds),'linked_outcomes':linked,'updated_at':stamp},ensure_ascii=False))
    if len(preds)<10 or linked<50:
        raise SystemExit('KBOAT_AI_PARSE_INCOMPLETE')

if __name__=='__main__': main()
