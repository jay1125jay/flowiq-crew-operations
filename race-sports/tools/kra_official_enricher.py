import html
import json
import re
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path

KST = timezone(timedelta(hours=9))
DATA = Path('race-sports/data/today.json')
UA = 'Mozilla/5.0 (RACE SPORTS ANALYTICS GitHub official-readonly)'
RUNNERS_URL = 'https://race.kra.co.kr/thisweekrace/ChulmaDate.do'
RESULTS_URL = 'https://race.kra.co.kr/thisweekrace/ThisWeekScoretableDailyScoretable.do?Act=05&Sub=2'
VENUES = ('서울', '부경', '영천', '제주')
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


def fetch(url, timeout=12, retries=2):
    last=None
    for i in range(retries):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept-Language':'ko-KR,ko;q=.9','Cache-Control':'no-cache','Connection':'close'})
            with urllib.request.urlopen(req,timeout=timeout) as r:return r.read().decode('utf-8','ignore')
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


def set_provider(payload,name,status,detail):
    payload['providers']=[p for p in payload.get('providers',[]) if p.get('provider')!=name]
    payload['providers'].append({'provider':name,'status':status,'detail':detail})


def main():
    payload=json.loads(DATA.read_text(encoding='utf-8')); today=payload.get('date'); observed=datetime.now(KST).isoformat()
    horse=[e for e in payload.get('events',[]) if e.get('sport')=='HORSE']
    runner_linked=0; result_linked=0
    try:
        raw=fetch(RUNNERS_URL); page_date,races=parse_runners(raw)
        for e in horse:
            venue=venue_of(e); info=races.get((venue,int(e.get('race_no') or 0))) if venue else None
            if not info:continue
            if info.get('start_time') and e.get('start_time') and info['start_time']!=e['start_time']:continue
            if info.get('outcomes'):
                old={o.get('key'):o for o in e.get('outcomes',[]) if o.get('key')}
                for o in info['outcomes']:
                    q=old.get(o['key'],{})
                    for k in ('model_p','model_source','model_updated_at','odds','odds_source','odds_capture_mode','odds_observed_at','final_rank'):
                        if q.get(k) is not None:o[k]=q[k]
                e['outcomes']=info['outcomes']; runner_linked+=1
        set_provider(payload,'HORSE_RUNNERS_KRA','PASS' if runner_linked else ('NO_TODAY_CARD' if not horse else 'UNLINKED'),{'page_date':page_date,'races_parsed':len(races),'linked':runner_linked,'source_url':RUNNERS_URL})
    except Exception as e:
        set_provider(payload,'HORSE_RUNNERS_KRA','FETCH_RETRY',{'error':f'{type(e).__name__}:{e}'[:220],'source_url':RUNNERS_URL})
    try:
        results=parse_results(fetch(RESULTS_URL))
        for e in horse:
            venue=venue_of(e); r=results.get((venue,int(e.get('race_no') or 0),today)) if venue else None
            if not r:continue
            out_by_num={int(o.get('number') or 0):o for o in e.get('outcomes',[])}
            top3=[]
            for rank,n in enumerate(r.pop('top_numbers',[])[:3],1):
                o=out_by_num.get(n); top3.append({'rank':rank,'number':n,'name':o.get('horse_name') if o else str(n)})
                if o:o['final_rank']=rank
            r['top3']=top3;r['updated_at']=observed;e['result']=r;e['status']='FINAL';result_linked+=1
        set_provider(payload,'HORSE_RESULT_KRA','PASS' if result_linked else ('NO_TODAY_CARD' if not horse else 'WAITING'),{'results_parsed':len(results),'confirmed':result_linked,'source_url':RESULTS_URL})
    except Exception as e:
        set_provider(payload,'HORSE_RESULT_KRA','FETCH_RETRY',{'error':f'{type(e).__name__}:{e}'[:220],'source_url':RESULTS_URL})
    DATA.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps({'KRA_ENRICH':'PASS','runner_linked':runner_linked,'result_linked':result_linked},ensure_ascii=False))


if __name__=='__main__':main()
