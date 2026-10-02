INLINE_KBOAT_ODDS_ENABLED = False
import json,re,html,urllib.request,time
from datetime import datetime,timezone,timedelta
from pathlib import Path

KST=timezone(timedelta(hours=9))
UA='Mozilla/5.0 (RACE SPORTS ANALYTICS GitHub official-readonly)'
KBOAT_UA='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'
OUT=Path('race-sports/data/today.json')

def now(): return datetime.now(KST)
def fetch(url,timeout=15,headers=None,retries=1):
    h={'User-Agent':UA,'Accept-Language':'ko-KR,ko;q=.9'}
    if headers:h.update(headers)
    last=None
    for i in range(max(1,retries)):
        try:
            req=urllib.request.Request(url,headers=h)
            with urllib.request.urlopen(req,timeout=timeout) as r:
                return r.read().decode('utf-8','ignore')
        except Exception as e:
            last=e
            if i+1<max(1,retries):time.sleep(1.2*(i+1))
    raise last

def kboat_fetch(url,timeout=15,retries=3):
    return fetch(url,timeout=timeout,retries=retries,headers={
        'User-Agent':KBOAT_UA,
        'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language':'ko-KR,ko;q=.9,en;q=.7',
        'Connection':'close',
        'Cache-Control':'no-cache'
    })

def textify(s):
    s=re.sub(r'<script[\s\S]*?</script>',' ',s,flags=re.I)
    s=re.sub(r'<style[\s\S]*?</style>',' ',s,flags=re.I)
    s=re.sub(r'<br\s*/?\s*>','\n',s,flags=re.I)
    s=re.sub(r'</(tr|td|th|div|p|li|h1|h2|h3|h4|option)>','\n',s,flags=re.I)
    s=re.sub(r'<[^>]+>',' ',s)
    s=html.unescape(s).replace('\r','')
    s=re.sub(r'[ \t]+',' ',s); s=re.sub(r'\n[ \t]+','\n',s); s=re.sub(r'\n{2,}','\n',s)
    return s

def status_for(start,result=None,live_window=35):
    if result:return 'FINAL'
    try: hh,mm=map(int,start.split(':'))
    except:return 'SCHEDULED'
    z=now(); d=z.hour*60+z.minute-(hh*60+mm)
    if d<0:return 'SCHEDULED'
    return 'LIVE' if d<=live_window else 'RESULT_PENDING'

def selected_date(raw,y):
    for m in re.finditer(r'<option[^>]*selected[^>]*>([\s\S]*?)</option>',raw,re.I):
        t=textify(m.group(1))
        q=re.search(r'(\d{2})월\s*(\d{2})일',t)
        if q:return f'{y}-{q.group(1)}-{q.group(2)}'
        q=re.search(r'(\d{4})[./-](\d{2})[./-](\d{2})',t)
        if q:return f'{q.group(1)}-{q.group(2)}-{q.group(3)}'
    return None

def parse_single_odds(raw,race_no):
    # Official KBOAT final-odds HTML has a dedicated <h3>단승식</h3> table.
    h=re.search(r'<h3[^>]*>\s*단승식\s*</h3>',raw,re.I)
    if h:
        sec=raw[h.end():h.end()+8000]
        tb=re.search(r'<tbody[^>]*>([\s\S]*?)</tbody>',sec,re.I)
        if tb:
            vals=[]
            for cell in re.findall(r'<td[^>]*>([\s\S]*?)</td>',tb.group(1),re.I):
                s=textify(cell).replace(',','').strip()
                m=re.search(r'(?<!\d)(\d+(?:\.\d+)?)(?!\d)',s)
                if m: vals.append(float(m.group(1)))
                if len(vals)>=6: break
            if len(vals)==6 and all(v>0 for v in vals): return vals
    # Text fallback for minor markup changes.
    t=textify(raw)
    pat=(r'단승식\s+1\s+2\s+3\s+4\s+5\s+6\s+'
         r'(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+'
         r'(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)')
    hits=list(re.finditer(pat,t,re.I))
    if hits:
        vals=[float(x) for x in hits[-1].groups()]
        if len(vals)==6 and all(v>0 for v in vals): return vals
    return None

def parse_boat_results(raw):
    t=textify(raw); marker=t.find('경주결과'); t=t[marker:] if marker>=0 else t
    ms=list(re.finditer(r'(?:^|\n)(\d{2})R\s*\n',t)); out={}
    for i,m in enumerate(ms):
        rn=int(m.group(1)); seg=t[m.start():(ms[i+1].start() if i+1<len(ms) else len(t))]
        lines=[x.strip() for x in seg.split('\n') if x.strip()]
        try:ri=lines.index(f'{rn:02d}R')
        except ValueError:continue
        if len(lines)<ri+7:continue
        try:top3=[{'rank':1,'number':int(lines[ri+1]),'name':lines[ri+2]},{'rank':2,'number':int(lines[ri+3]),'name':lines[ri+4]},{'rank':3,'number':int(lines[ri+5]),'name':lines[ri+6]}]
        except:continue
        rest='\n'.join(lines[ri+7:]); bets=[{'winner':a.replace(' ',''),'odds':float(b)} for a,b in re.findall(r'\(([^)]+)\)\s*\n?\s*(\d+(?:\.\d+)?)',rest)]
        names=['단승식','연승식','연승식','쌍승식','복승식','삼복승식','쌍복승식','삼쌍승식']
        out[rn]={'official':True,'status':'CONFIRMED','top3':top3,'markets':[{'market':names[k],**bets[k]} for k in range(min(len(bets),len(names)))],'source':'KBOAT_RESULT_OFFICIAL'}
    return out

def prior_events(date):
    if not OUT.exists():return {}
    try:
        p=json.loads(OUT.read_text(encoding='utf-8'))
        if p.get('date')!=date:return {}
        return {e.get('id'):e for e in p.get('events',[]) if e.get('id')}
    except:return {}

def carry_prior_odds(event,old):
    if not old:return
    old_out={o.get('key'):o for o in old.get('outcomes',[])}
    for o in event.get('outcomes',[]):
        q=old_out.get(o.get('key'),{})
        for k in ('odds','odds_source','odds_observed_at'):
            if q.get(k) is not None:o[k]=q[k]
    if old.get('odds_history'):event['odds_history']=old['odds_history'][-120:]

def apply_odds(event,vals,z):
    snap={f'N{i+1}':float(vals[i]) for i in range(min(6,len(vals)))}
    hist=list(event.get('odds_history',[]))
    prev=hist[-1].get('odds',{}) if hist else {}
    if prev!=snap:
        hist.append({'observed_at':z.isoformat(),'market':'단승식','source':'KBOAT_FINAL_SINGLE_AUTO','odds':snap})
        event['odds_history']=hist[-120:]
    for o in event.get('outcomes',[]):
        n=int(o.get('number') or 0)
        if 1<=n<=6:
            o['odds']=float(vals[n-1]);o['odds_source']='KBOAT_FINAL_SINGLE_AUTO';o['odds_observed_at']=z.isoformat()

def collect_boat(z,errors):
    date=z.strftime('%Y-%m-%d'); y=z.year; w=z.isocalendar().week; events=[]; day_used=None
    for day in (1,2,3):
        url=f'https://www.kboat.or.kr/race/card/decision/{y}/{w}/{day}'
        try:
            raw=kboat_fetch(url,retries=2); sd=selected_date(raw,y)
            if sd!=date:continue
            t=textify(raw); hs=list(re.finditer(r'제\s*(\d{2})경주\s*\(출발시간\s*(\d{1,2}:\d{2})\)',t))
            for i,a in enumerate(hs):
                seg=t[a.start():(hs[i+1].start() if i+1<len(hs) else min(len(t),a.start()+12000))]; rr={}
                for m in re.finditer(r'(?:^|\s)([1-6])\s+([가-힣]{2,5})\s+\d{1,2}기/',seg):
                    rr.setdefault(int(m.group(1)),m.group(2))
                    if len(rr)>=6:break
                if len(rr)<2:continue
                rn=int(a.group(1)); tm=a.group(2)
                events.append({'id':f'BOAT-{date.replace("-","")}-{w}-{day}-{rn:02d}','sport':'BOAT','provider':'KBOAT','competition':f'미사리 경정 {w}회차 {day}일차','event_date':date,'start_time':tm,'race_no':rn,'status':'SCHEDULED','title':f'{rn:02d}경주','market_type':'RUNNERS','outcomes':[{'key':f'N{n}','name':f'{n} {rr[n]}','number':n,'model_p':None} for n in sorted(rr)],'source_url':url})
            day_used=day;break
        except Exception as e:errors.append(f'BOAT card day{day}:{e}')
    oldmap=prior_events(date)
    for e in events:carry_prior_odds(e,oldmap.get(e['id']))
    results={}
    if day_used and events:
        try:results=parse_boat_results(kboat_fetch(f'https://www.kboat.or.kr/race/result/general/{y}/{w}/{day_used}/01',retries=2))
        except Exception as e:errors.append(f'BOAT result:{e}')
        cur=z.hour*60+z.minute
        for e in events:
            r=results.get(e['race_no']); e['status']=status_for(e['start_time'],r,35)
            if r:
                r['source_url']=f'https://www.kboat.or.kr/race/result/general/{y}/{w}/{day_used}/{e["race_no"]:02d}'; r['updated_at']=z.isoformat(); e['result']=r
                for o in e['outcomes']:
                    hit=next((x for x in r['top3'] if x['number']==o['number']),None)
                    if hit:o['final_rank']=hit['rank']
            hh,mm=map(int,e['start_time'].split(':')); delta=hh*60+mm-cur
            if INLINE_KBOAT_ODDS_ENABLED and -35<=delta<=120 and not r:
                try:
                    odds_url=f'https://kboat.or.kr/race/dividendrate/final/{y}/{w}/{day_used}/{e["race_no"]:02d}'
                    vals=parse_single_odds(kboat_fetch(odds_url,timeout=12,retries=3),e['race_no'])
                    if vals:apply_odds(e,vals,z)
                    else:errors.append(f'BOAT odds {e["race_no"]}:NO_SINGLE_TABLE')
                except Exception as x:errors.append(f'BOAT odds {e["race_no"]}:{x}')
    odds_events=sum(1 for e in events if any(float(o.get('odds',0) or 0)>0 for o in e.get('outcomes',[])))
    providers=[{'provider':'BOAT_KBOAT','status':'PASS' if events else 'NO_TODAY_CARD','detail':{'week':w,'day':day_used,'published':len(events)}},{'provider':'BOAT_RESULT_KBOAT','status':'PASS','detail':{'confirmed':len(results)}},{'provider':'BOAT_ODDS_KBOAT','status':'PASS' if odds_events else 'WAITING','detail':{'market':'단승식','window':'경기 120분 전~35분 후','odds_events':odds_events,'source':'KBOAT_FINAL'}}]
    return events,providers

def collect_cycle(z,errors):
    if z.weekday() not in (4,5,6):return [],[{'provider':'CYCLE_KCYCLE','status':'NO_RACE_WEEKDAY','detail':{}}]
    day={4:1,5:2,6:3}[z.weekday()]; y=z.year; w=z.isocalendar().week; date=z.strftime('%Y-%m-%d'); url=f'https://www.kcycle.or.kr/race/card/decision/{y}/{w}/{day}'
    try:
        t=textify(fetch(url)); hs=list(re.finditer(r'(광명|창원|부산)\s*(\d{2})경주\s*\(([^)]*?)(\d{1,2}:\d{2})\)',t)); out=[]
        for i,a in enumerate(hs):
            seg=t[a.start():(hs[i+1].start() if i+1<len(hs) else min(len(t),a.start()+12000))]; rr={}
            for m in re.finditer(r'(?:^|\s)([1-7])\s+([가-힣](?:\s*[가-힣]){1,4})\s+\d{1,2}기',seg):
                rr.setdefault(int(m.group(1)),re.sub(r'\s+','',m.group(2)))
                if len(rr)>=7:break
            if len(rr)<2:continue
            rn=int(a.group(2)); tm=a.group(4)
            out.append({'id':f'CYCLE-{date.replace("-","")}-{a.group(1)}-{rn:02d}','sport':'CYCLE','provider':'KCYCLE','competition':a.group(1)+' 경륜','event_date':date,'start_time':tm,'race_no':rn,'status':status_for(tm,None,35),'title':a.group(1)+f' {rn:02d}경주','market_type':'RUNNERS','outcomes':[{'key':f'N{n}','name':f'{n} {rr[n]}','number':n,'model_p':None} for n in sorted(rr)],'source_url':url})
        return out,[{'provider':'CYCLE_KCYCLE','status':'PASS','detail':{'week':w,'day':day,'published':len(out)}}]
    except Exception as e:errors.append(f'CYCLE:{e}');return [],[{'provider':'CYCLE_KCYCLE','status':'FAIL','detail':{'error':str(e)}}]

def collect_bull(z,errors):
    url='https://www.cpc.or.kr/cpc/module/game/gameCard/confirmed/index.do?menu_idx=52'; date=z.strftime('%Y-%m-%d')
    try:
        t=textify(fetch(url)); a=re.search(r'(\d{4})년도\s*(\d+)회차\s*(\d+)일차\s*\((\d{2})월\s*(\d{2})일\)표',t)
        if not a:return [],[{'provider':'BULL_CPC','status':'FAIL','detail':{'reason':'HEADER_NOT_PARSED'}}]
        card_date=f'{a.group(1)}-{a.group(4)}-{a.group(5)}'
        if card_date!=date:return [],[{'provider':'BULL_CPC','status':'NO_TODAY_CARD','detail':{'latest_card_date':card_date}}]
        out=[]
        rx=re.compile(r'(\d{2})경기\s*([갑을병])?\s*\(시작시간:\s*([^)]+)\)[\s\S]*?홍\s+([가-힣A-Za-z0-9_-]+)[\s\S]*?청\s+([가-힣A-Za-z0-9_-]+)')
        for m in rx.finditer(t):
            q=re.search(r'(\d{1,2})\s*[:시]\s*(\d{1,2})',m.group(3))
            if not q:continue
            tm=f'{int(q.group(1)):02d}:{int(q.group(2)):02d}'; rn=int(m.group(1))
            out.append({'id':f'BULL-{date.replace("-","")}-{a.group(2)}-{a.group(3)}-{rn:02d}','sport':'BULL','provider':'CPC','competition':f'청도 소싸움 {a.group(2)}회차 {a.group(3)}일차','event_date':date,'start_time':tm,'race_no':rn,'status':status_for(tm,None,90),'title':f'{rn:02d}경기','left':m.group(4),'right':m.group(5),'left_tag':'홍','right_tag':'청','market_type':'THREE_WAY','outcomes':[{'key':'RED','name':'홍','model_p':None},{'key':'DRAW','name':'무','model_p':None},{'key':'BLUE','name':'청','model_p':None}],'source_url':url})
        return out,[{'provider':'BULL_CPC','status':'PASS','detail':{'published':len(out),'card_date':card_date}}]
    except Exception as e:errors.append(f'BULL:{e}');return [],[{'provider':'BULL_CPC','status':'FAIL','detail':{'error':str(e)}}]

def collect_horse(z,errors):
    url='https://race.kra.co.kr/thisweekrace/ThisWeekDetailInfoList.do?Act=01&Sub=2&meet='; date=z.strftime('%Y-%m-%d'); ds=z.strftime('%Y/%m/%d')
    try:
        t=textify(fetch(url)); out=[]
        for m in re.finditer(r'(서울|부경|영천|제주)\s+(\d{4}/\d{2}/\d{2})\([^)]*\)\s+(\d{1,2})\s+([^\n]+?)\s+(\d{3,4})\s+(\d{1,2})\s+([^\n]+?)\s+(\d{1,2}:\d{2})',t):
            if m.group(2)!=ds:continue
            venue=m.group(1);rn=int(m.group(3));tm=m.group(8)
            out.append({'id':f'HORSE-{date.replace("-","")}-{venue}-{rn:02d}','sport':'HORSE','provider':'KRA','competition':venue+' 경마','event_date':date,'start_time':tm,'race_no':rn,'status':status_for(tm,None,45),'title':f'{rn:02d}경주','market_type':'RUNNERS','outcomes':[],'field_size':int(m.group(6)),'distance_m':int(m.group(5)),'source_url':url})
        return out,[{'provider':'HORSE_KRA','status':'PASS' if out else 'NO_TODAY_CARD','detail':{'published':len(out),'runner_detail':'PENDING_PUBLIC_PAGE_PARSER'}}]
    except Exception as e:errors.append(f'HORSE:{e}');return [],[{'provider':'HORSE_KRA','status':'FAIL','detail':{'error':str(e)}}]

def main():
    z=now(); errors=[]; events=[]; providers=[]
    for fn in (collect_horse,collect_cycle,collect_boat,collect_bull):
        es,ps=fn(z,errors);events.extend(es);providers.extend(ps)
    events.sort(key=lambda e:(e.get('start_time','99:99'),e.get('sport','')))
    payload={'date':z.strftime('%Y-%m-%d'),'date_display':z.strftime('%Y.%m.%d'),'time':z.strftime('%H:%M:%S'),'generated_at':z.isoformat(),'mode':'GITHUB_4SPORT_OFFICIAL','sample_data':False,'events':events,'providers':providers,'errors':errors[-20:]}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps({'date':payload['date'],'events':len(events),'by_sport':{s:sum(1 for e in events if e['sport']==s) for s in ('HORSE','CYCLE','BOAT','BULL')},'odds_events':sum(1 for e in events if any(float(o.get('odds',0) or 0)>0 for o in e.get('outcomes',[]))),'errors':len(errors)},ensure_ascii=False))

if __name__=='__main__':main()
