import json,re,html,urllib.request
from pathlib import Path

UA='Mozilla/5.0 (RACE SPORTS ANALYTICS official-readonly)'
DATA=Path('race-sports/data/today.json')
URL='https://www.kboat.or.kr/rankingpredict'

def fetch(url,timeout=20):
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept-Language':'ko-KR,ko;q=.9','Cache-Control':'no-cache'})
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
    sm=re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*기준',t)
    if sm: stamp=sm.group(1)
    markers=list(re.finditer(r'(?<!\d)(\d{2})R(?!\d)',t))
    out={}
    for i,m in enumerate(markers):
        rn=int(m.group(1))
        seg=t[m.end():(markers[i+1].start() if i+1<len(markers) else len(t))]
        pairs=[]; seen=set()
        for n,pct in re.findall(r'(?<!\d)([1-6])\s+(\d{1,2}(?:\.\d+)?)%',seg):
            n=int(n); v=float(pct)/100.0
            if n in seen: continue
            seen.add(n); pairs.append((n,v))
            if len(pairs)==6: break
        if len(pairs)==6:
            total=sum(v for _,v in pairs)
            if 0.98<=total<=1.02:
                out[rn]={f'N{n}':v for n,v in pairs}
    return out,stamp

def main():
    payload=json.loads(DATA.read_text(encoding='utf-8'))
    today=str(payload.get('date') or '')
    boat=[e for e in payload.get('events',[]) if e.get('sport')=='BOAT']
    if not boat:
        providers=[x for x in payload.get('providers',[]) if x.get('provider')!='BOAT_AI_KBOAT']
        providers.append({'provider':'BOAT_AI_KBOAT','status':'NO_TODAY_CARD','detail':{'snapshot_date':today,'source_url':URL,'meaning':'official AI win probability'}})
        payload['providers']=providers
        DATA.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
        print(json.dumps({'status':'NO_TODAY_CARD','linked_outcomes':0,'snapshot_date':today},ensure_ascii=False))
        return

    preds,stamp=parse(fetch(URL))
    source_date=stamp[:10] if stamp else None
    source_fresh=bool(source_date and source_date==today)
    linked=0
    linked_events=0
    expected=sum(len(e.get('outcomes',[])) for e in boat)

    for e in boat:
        p=preds.get(int(e.get('race_no') or 0),{}) if source_fresh else {}
        event_linked=0
        if p:
            for o in e.get('outcomes',[]):
                if o.get('key') in p:
                    o['model_p']=p[o['key']]
                    o['model_source']='KBOAT_AI_OFFICIAL'
                    o['model_updated_at']=stamp
                    linked+=1; event_linked+=1
        if event_linked==len(e.get('outcomes',[])) and event_linked>0:
            linked_events+=1
            e.pop('model_stale',None); e.pop('model_stale_reason',None)
        else:
            e['model_stale']=True
            e['model_stale_reason']='KBOAT_AI_SOURCE_DATE_MISMATCH' if not source_fresh else 'KBOAT_AI_EVENT_INCOMPLETE'

    complete=source_fresh and bool(preds) and linked==expected and linked_events==len(boat)
    status='PASS' if complete else ('STALE_SOURCE' if preds and not source_fresh else 'INCOMPLETE')
    providers=[x for x in payload.get('providers',[]) if x.get('provider')!='BOAT_AI_KBOAT']
    providers.append({'provider':'BOAT_AI_KBOAT','status':status,'detail':{'races':len(preds),'linked_events':linked_events,'linked_outcomes':linked,'expected_outcomes':expected,'updated_at':stamp,'source_date':source_date,'snapshot_date':today,'source_fresh':source_fresh,'source_url':URL,'meaning':'official AI win probability'}})
    payload['providers']=providers
    DATA.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps({'status':status,'ai_races':len(preds),'linked_events':linked_events,'linked_outcomes':linked,'expected_outcomes':expected,'updated_at':stamp,'source_date':source_date,'snapshot_date':today},ensure_ascii=False))
    if not complete:
        raise SystemExit('KBOAT_AI_NOT_CURRENT_AND_COMPLETE')

if __name__=='__main__': main()
