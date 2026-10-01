import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path

KST = timezone(timedelta(hours=9))
DATA = Path('race-sports/data/today.json')
UA = 'Mozilla/5.0 (RACE SPORTS ANALYTICS GitHub official-readonly)'
RUNNERS_URL = 'https://race.kra.co.kr/thisweekrace/ChulmaDate.do'
RESULTS_URL = 'https://race.kra.co.kr/thisweekrace/ThisWeekScoretableDailyScoretable.do?Act=05&Sub=2'
DETAIL_URL = 'https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet={meet}&realRcDate={date}&realRcNo={race_no}'
KRA_PRE_ODDS_ENDPOINTS = (
    ('KRA_API301_OFFICIAL', 'https://apis.data.go.kr/B551015/API301/Dividend_rate_total'),
    ('KRA_API27_OFFICIAL', 'https://apis.data.go.kr/B551015/API27_1/winPredictionRateInfo_1'),
)
VENUES = ('서울', '부경', '부산경남', '영천', '제주')
MEET_CODE = {'서울': '1', '제주': '2', '부경': '3', '부산경남': '3', '영천': '4'}
CIRCLED = dict(zip('①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳', range(1, 21)))


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_tr = False
        self.in_cell = False
        self.cell = []
        self.row = []
        self.rows = []
        self.selected = False
        self.option = []
        self.selected_options = []
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower(); attrs = dict(attrs)
        if tag == 'tr': self.in_tr = True; self.row = []
        elif tag in ('td', 'th') and self.in_tr: self.in_cell = True; self.cell = []
        elif tag == 'option': self.selected = 'selected' in attrs or attrs.get('selected') is not None; self.option = []
        if tag in ('br','p','div','h1','h2','h3','h4','li'): self.text_parts.append('\n')

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ('td','th') and self.in_cell:
            self.row.append(clean(''.join(self.cell))); self.in_cell = False; self.cell = []
        elif tag == 'tr' and self.in_tr:
            if self.row: self.rows.append(self.row[:])
            self.in_tr = False; self.row = []
        elif tag == 'option':
            if self.selected: self.selected_options.append(clean(''.join(self.option)))
            self.selected = False; self.option = []
        if tag in ('p','div','h1','h2','h3','h4','li','tr'): self.text_parts.append('\n')

    def handle_data(self, data):
        if self.in_cell: self.cell.append(data)
        if self.selected: self.option.append(data)
        self.text_parts.append(data)

    def text(self):
        s = html.unescape(''.join(self.text_parts)).replace('\r','')
        s = re.sub(r'[ \t]+',' ',s); s = re.sub(r'\n[ \t]+','\n',s)
        return re.sub(r'\n{2,}','\n',s)


def clean(s): return re.sub(r'\s+',' ',html.unescape(str(s))).strip()


def decode_http_body(data, headers=None):
    candidates=[]
    try:
        c=headers.get_content_charset() if headers is not None else None
        if c:candidates.append(c)
    except:pass
    m=re.search(br'charset\s*=\s*["\']?([A-Za-z0-9._-]+)',data[:4096],re.I)
    if m:
        try:candidates.append(m.group(1).decode('ascii','ignore'))
        except:pass
    candidates += ['utf-8','euc-kr','cp949']
    seen=set()
    for enc in candidates:
        key=str(enc).lower()
        if key in seen:continue
        seen.add(key)
        try:return data.decode(enc)
        except:continue
    return data.decode('utf-8','ignore')


def fetch(url, timeout=12, retries=2):
    last=None
    for i in range(retries):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept-Language':'ko-KR,ko;q=.9','Cache-Control':'no-cache','Connection':'close'})
            with urllib.request.urlopen(req,timeout=timeout) as r:return decode_http_body(r.read(),r.headers)
        except Exception as e:
            last=e
            if i+1<retries: time.sleep(1.5)
    raise last


def parsed(raw):
    p=TableParser();p.feed(raw);return p,p.text()


def selected_date(p,text):
    for x in p.selected_options:
        m=re.search(r'(\d{4})[./-](\d{2})[./-](\d{2})',x)
        if m:return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
        m=re.search(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일',x)
        if m:return f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    m=re.search(r'기준일자[^\d]*(\d{4})[./-](\d{1,2})[./-](\d{1,2})',text)
    if m:return f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    return None


def venue_of(e):
    s=str(e.get('competition') or '')+' '+str(e.get('id') or '')
    return next((v for v in VENUES if v in s),None)


def parse_runners(raw):
    p,text=parsed(raw); date=selected_date(p,text); races={}; current=None
    for row in p.rows:
        if len(row)>=2 and row[0] in VENUES and re.search(r'제\s*\d+경주',row[1]):
            m=re.search(r'제\s*(\d+)경주',row[1]); tm=None
            for c in row:
                q=re.search(r'출발\s*(\d{1,2}:\d{2})',c)
                if q:tm=q.group(1)
            if m:
                current=(row[0],int(m.group(1)))
                races.setdefault(current,{'start_time':tm,'outcomes':[]})
            continue
        if current and row and re.fullmatch(r'\d{1,2}',row[0] or '') and len(row)>=7:
            n=int(row[0])
            if not 1<=n<=20:continue
            races[current]['outcomes'].append({
                'key':f'N{n}','number':n,'name':f'{n} {row[1]}','horse_name':row[1],
                'origin':row[2] if len(row)>2 else None,'sex':row[3] if len(row)>3 else None,
                'age':float(row[4]) if len(row)>4 and re.fullmatch(r'\d+(?:\.\d+)?',row[4]) else None,
                'assigned_weight':float(row[5]) if len(row)>5 and re.fullmatch(r'\d+(?:\.\d+)?',row[5]) else None,
                'jockey':row[6] if len(row)>6 else None,'trainer':row[7] if len(row)>7 else None,
                'owner':row[8] if len(row)>8 else None,'model_p':None,
            })
    return date,races


def nums_from_cell(s):
    out=[]
    for ch in str(s):
        if ch in CIRCLED: out.append(CIRCLED[ch])
    return out


def odds_pairs(s):
    text=clean(s); nums=nums_from_cell(text); vals=[float(x) for x in re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])', re.sub(r'[①-⑳]',' ',text))]
    return nums,vals


def parse_results(raw):
    p,text=parsed(raw); out={}
    for row in p.rows:
        if len(row)<4 or row[0] not in VENUES:continue
        dm=re.search(r'(\d{4})/(\d{2})/(\d{2})',row[1])
        if not dm or not re.fullmatch(r'\d{1,2}',row[2] or ''):continue
        date=f'{dm.group(1)}-{dm.group(2)}-{dm.group(3)}'; rn=int(row[2]); markets=[]
        names=['단승식','연승식','복승식','쌍승식','복연승식','삼복승식','삼쌍승식']
        cells=row[3:10]
        for i,c in enumerate(cells):
            if i>=len(names):break
            ns,vs=odds_pairs(c)
            if not ns or not vs:continue
            if names[i]=='연승식':
                for j,v in enumerate(vs[:len(ns)]):markets.append({'market':'연승식','winner':str(ns[j]),'odds':v})
            elif names[i]=='복연승식':
                pass
            else:
                winner='-'.join(map(str,ns[:3]))
                markets.append({'market':names[i],'winner':winner,'odds':vs[-1]})
        if not markets:continue
        single=next((m for m in markets if m['market']=='단승식'),None)
        triple=next((m for m in markets if m['market']=='삼쌍승식'),None)
        top_nums=[]
        if triple: top_nums=[int(x) for x in triple['winner'].split('-') if x.isdigit()]
        elif single: top_nums=[int(single['winner'])]
        out[(row[0],rn,date)]={'markets':markets,'top_numbers':top_nums,'official':True,'status':'CONFIRMED','source':'KRA_SCORETABLE_OFFICIAL','source_url':RESULTS_URL}
    return out


def parse_detail_runner_odds(raw):
    p,_=parsed(raw); header=None; out={}
    for row in p.rows:
        norm=[clean(x).replace(' ','') for x in row]
        if '순위' in norm and '마번' in norm and '단승' in norm and '연승' in norm:
            try:header={'rank':norm.index('순위'),'number':norm.index('마번'),'single':norm.index('단승'),'place':norm.index('연승')}
            except ValueError:header=None
            continue
        if not header:continue
        need=max(header.values())
        if len(row)<=need:continue
        rs=clean(row[header['rank']]);ns=clean(row[header['number']])
        if not re.fullmatch(r'\d{1,2}',rs) or not re.fullmatch(r'\d{1,2}',ns):continue
        n=int(ns)
        try:single=float(clean(row[header['single']]).replace(',',''))
        except:single=None
        try:place=float(clean(row[header['place']]).replace(',',''))
        except:place=None
        if single is None and place is None:continue
        out[n]={'final_rank':int(rs),'final_odds':single,'final_place_odds':place}
    return out


def normalize_date(v):
    s=re.sub(r'\D','',str(v or ''))
    return s[:8] if len(s)>=8 else ''


def row_value(row,names):
    low={str(k).lower().replace('_',''):v for k,v in row.items()}
    for n in names:
        key=n.lower().replace('_','')
        if key in low and str(low[key]).strip()!='':return low[key]
    return None


def api_items(raw):
    s=raw.lstrip()
    if s.startswith('{') or s.startswith('['):
        obj=json.loads(raw)
        if isinstance(obj,list):return [x for x in obj if isinstance(x,dict)]
        for path in (('response','body','items','item'),('response','body','item'),('body','items','item'),('items','item')):
            cur=obj;ok=True
            for k in path:
                if isinstance(cur,dict) and k in cur:cur=cur[k]
                else:ok=False;break
            if ok:
                if isinstance(cur,dict):return [cur]
                if isinstance(cur,list):return [x for x in cur if isinstance(x,dict)]
        return []
    root=ET.fromstring(raw)
    return [{c.tag:(c.text or '') for c in item} for item in root.findall('.//item')]


def make_api_url(base,key,date,meet,race_no):
    params={
        'pageNo':'1','numOfRows':'200','resultType':'json','_type':'json',
        'rcDate':date.replace('-',''),'rc_date':date.replace('-',''),
        'rcNo':str(race_no),'rc_no':str(race_no),'meet':str(meet),
    }
    q=urllib.parse.urlencode(params);safe_key=urllib.parse.quote(str(key).strip(),safe='%')
    return f'{base}?serviceKey={safe_key}&{q}'


def parse_pre_single_odds(rows,date,meet,race_no,allowed_numbers):
    out={}
    for row in rows:
        row_date=row_value(row,['rcDate','rc_date','raceDate','race_date','date'])
        if row_date and normalize_date(row_date)!=date.replace('-',''):continue
        row_race=row_value(row,['rcNo','rc_no','raceNo','race_no'])
        if row_race is not None:
            try:
                if int(float(str(row_race)))!=int(race_no):continue
            except:continue
        row_meet=row_value(row,['meet','meetCd','meet_cd','sale_race','racecourse'])
        if row_meet is not None:
            x=str(row_meet).strip()
            if x.isdigit() and int(x)!=int(meet):continue
        n=row_value(row,['chulNo','chul_no','horseNo','horse_no','hrNo','hr_no','gateNo','gate_no'])
        try:n=int(float(str(n)))
        except:continue
        if n not in allowed_numbers:continue
        odd=row_value(row,['winOdds','win_odds','singleOdds','single_odds','odds','dividendRate','dividend_rate','allocRate','alloc_rate'])
        try:v=float(str(odd).replace(',',''))
        except:continue
        if v<=0:continue
        out[n]=v
    return out


def apply_pre_odds(event,odds,source,observed):
    if event.get('status')!='SCHEDULED':return 0
    by_num={int(o.get('number') or 0):o for o in event.get('outcomes',[])};mapped=0
    for n,v in odds.items():
        o=by_num.get(int(n))
        if not o:continue
        o['odds']=float(v);o['odds_source']=source;o['odds_capture_mode']='PRE_RACE';o['odds_observed_at']=observed;mapped+=1
    if mapped:
        snap={f'N{n}':float(v) for n,v in sorted(odds.items()) if n in by_num}
        hist=list(event.get('odds_history',[]));prev=hist[-1].get('odds',{}) if hist else {}
        if snap and snap!=prev:
            hist.append({'observed_at':observed,'market':'단승식','source':source,'capture_mode':'PRE_RACE','odds':snap})
            event['odds_history']=hist[-120:]
    return mapped


def set_provider(payload,name,status,detail):
    payload['providers']=[p for p in payload.get('providers',[]) if p.get('provider')!=name]
    payload['providers'].append({'provider':name,'status':status,'detail':detail})


def self_test():
    # Real values copied from KRA official 2018-07-08 Seoul R4 result table.
    fixture='''<table><tr><th>순위</th><th>마번</th><th>마명</th><th>산지</th><th>성별</th><th>연령</th><th>중량</th><th>레이팅</th><th>기수명</th><th>조교사명</th><th>마주명</th><th>도착차</th><th>마체중</th><th>단승</th><th>연승</th><th>장구현황</th></tr><tr><td>1</td><td>7</td><td>가라가라가</td><td>한</td><td>수</td><td>3세</td><td>56</td><td>32</td><td>안토니오</td><td>강환민</td><td>서창식</td><td></td><td>457(-10)</td><td>5.0</td><td>1.9</td><td></td></tr><tr><td>2</td><td>1</td><td>새벽장군</td><td>한</td><td>거</td><td>3세</td><td>55</td><td>30</td><td>누네스</td><td>박대흥</td><td>죽마조합</td><td>1½</td><td>491(-10)</td><td>3.2</td><td>1.4</td><td></td></tr></table>'''
    rows=parse_detail_runner_odds(fixture)
    assert rows.get(7,{}).get('final_odds')==5.0,rows
    assert rows.get(7,{}).get('final_place_odds')==1.9,rows
    assert rows.get(1,{}).get('final_odds')==3.2,rows
    print(json.dumps({'KRA_SELF_TEST':'PASS','fixture_source':'KRA_OFFICIAL_2018-07-08_SEOUL_R4','rows':len(rows)},ensure_ascii=False))


def main():
    payload=json.loads(DATA.read_text(encoding='utf-8'));today=payload.get('date');observed=datetime.now(KST).isoformat()
    horse=[e for e in payload.get('events',[]) if e.get('sport')=='HORSE']
    runner_linked=0;result_linked=0;final_odds_linked=0;pre_odds_events=0;pre_odds_runners=0

    try:
        raw=fetch(RUNNERS_URL);page_date,races=parse_runners(raw)
        if page_date and page_date!=today:races={}
        for e in horse:
            venue=venue_of(e);info=races.get((venue,int(e.get('race_no') or 0))) if venue else None
            if not info:continue
            if info.get('start_time') and e.get('start_time') and info['start_time']!=e['start_time']:continue
            if info.get('outcomes'):
                old={o.get('key'):o for o in e.get('outcomes',[]) if o.get('key')}
                for o in info['outcomes']:
                    q=old.get(o['key'],{})
                    for k in ('model_p','model_source','model_updated_at','odds','odds_source','odds_capture_mode','odds_observed_at','final_rank','final_odds','final_place_odds','final_odds_source'):
                        if q.get(k) is not None:o[k]=q[k]
                e['outcomes']=info['outcomes'];runner_linked+=1
        set_provider(payload,'HORSE_RUNNERS_KRA','PASS' if runner_linked else ('NO_TODAY_CARD' if not horse else 'UNLINKED'),{'page_date':page_date,'races_parsed':len(races),'linked':runner_linked,'source_url':RUNNERS_URL})
    except Exception as e:
        set_provider(payload,'HORSE_RUNNERS_KRA','FETCH_RETRY',{'error':f'{type(e).__name__}:{e}'[:220],'source_url':RUNNERS_URL})

    api_key=os.environ.get('KRA_API_KEY','').strip()
    if not horse:
        set_provider(payload,'HORSE_PRE_ODDS_KRA','NO_TODAY_CARD',{'linked_events':0,'linked_runners':0})
    elif not api_key:
        set_provider(payload,'HORSE_PRE_ODDS_KRA','API_KEY_MISSING',{'linked_events':0,'linked_runners':0,'required_secret':'KRA_API_KEY'})
    else:
        api_errors=[];endpoint_hits={}
        for e in horse:
            if e.get('status')!='SCHEDULED' or e.get('event_date')!=today:continue
            venue=venue_of(e);meet=MEET_CODE.get(venue);rn=int(e.get('race_no') or 0)
            allowed={int(o.get('number') or 0) for o in e.get('outcomes',[]) if int(o.get('number') or 0)>0}
            if not meet or not rn or len(allowed)<2:continue
            hit={};used=None
            for source,base in KRA_PRE_ODDS_ENDPOINTS:
                try:
                    rows=api_items(fetch(make_api_url(base,api_key,today,meet,rn),timeout=10,retries=1))
                    hit=parse_pre_single_odds(rows,today,meet,rn,allowed)
                    endpoint_hits[source]=endpoint_hits.get(source,0)+(1 if hit else 0)
                    if len(hit)>=2:used=source;break
                except Exception as x:
                    api_errors.append(f'{source}:{venue}:{rn}:{type(x).__name__}:{x}'[:220])
            if used and hit:
                mapped=apply_pre_odds(e,hit,used+'_PRE_CAPTURE',observed)
                if mapped:pre_odds_events+=1;pre_odds_runners+=mapped
        status='PASS' if pre_odds_events else ('FETCH_RETRY' if api_errors else 'WAITING')
        set_provider(payload,'HORSE_PRE_ODDS_KRA',status,{'linked_events':pre_odds_events,'linked_runners':pre_odds_runners,'endpoint_hits':endpoint_hits,'errors':api_errors[:3]})

    try:
        results=parse_results(fetch(RESULTS_URL))
        for e in horse:
            venue=venue_of(e);r=results.get((venue,int(e.get('race_no') or 0),today)) if venue else None
            if not r:continue
            out_by_num={int(o.get('number') or 0):o for o in e.get('outcomes',[])};top3=[]
            for rank,n in enumerate(r.pop('top_numbers',[])[:3],1):
                o=out_by_num.get(n);top3.append({'rank':rank,'number':n,'name':o.get('horse_name') if o else str(n)})
                if o:o['final_rank']=rank
            r['top3']=top3;r['updated_at']=observed;e['result']=r;e['status']='FINAL';result_linked+=1
        set_provider(payload,'HORSE_RESULT_KRA','PASS' if result_linked else ('NO_TODAY_CARD' if not horse else 'WAITING'),{'results_parsed':len(results),'confirmed':result_linked,'source_url':RESULTS_URL})
    except Exception as e:
        set_provider(payload,'HORSE_RESULT_KRA','FETCH_RETRY',{'error':f'{type(e).__name__}:{e}'[:220],'source_url':RESULTS_URL})

    detail_errors=[]
    for e in horse:
        if e.get('status')!='FINAL':continue
        venue=venue_of(e);meet=MEET_CODE.get(venue);rn=int(e.get('race_no') or 0)
        if not meet or not rn:continue
        url=DETAIL_URL.format(meet=meet,date=today.replace('-',''),race_no=rn)
        try:
            rows=parse_detail_runner_odds(fetch(url,timeout=10,retries=1));by_num={int(o.get('number') or 0):o for o in e.get('outcomes',[])};mapped=0
            for n,v in rows.items():
                o=by_num.get(n)
                if not o:continue
                if v.get('final_odds') is not None:o['final_odds']=v['final_odds']
                if v.get('final_place_odds') is not None:o['final_place_odds']=v['final_place_odds']
                o['final_odds_source']='KRA_SCORETABLE_DETAIL_OFFICIAL';mapped+=1
            if mapped:final_odds_linked+=1
        except Exception as x:
            detail_errors.append(f'{venue}:{rn}:{type(x).__name__}:{x}'[:220])
    set_provider(payload,'HORSE_FINAL_ODDS_KRA','PASS' if final_odds_linked else ('NO_TODAY_CARD' if not horse else ('FETCH_RETRY' if detail_errors else 'WAITING')),{'linked_events':final_odds_linked,'errors':detail_errors[:3],'source':'KRA_SCORETABLE_DETAIL_OFFICIAL'})

    DATA.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps({'KRA_ENRICH':'PASS','runner_linked':runner_linked,'pre_odds_events':pre_odds_events,'pre_odds_runners':pre_odds_runners,'result_linked':result_linked,'final_odds_linked':final_odds_linked},ensure_ascii=False))


if __name__=='__main__':
    if '--self-test' in sys.argv:self_test()
    else:main()
