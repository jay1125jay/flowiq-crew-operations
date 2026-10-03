#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timezone, timedelta
from html.parser import HTMLParser
from typing import Any

KST=timezone(timedelta(hours=9))
ESPN_BASE="https://site.api.espn.com/apis/site/v2/sports"
KOVO_BASE="https://www.kovo.co.kr/game/v-league/11110_schedule_list.asp"

SPORTS={
    "SOCCER":{"provider":"ESPN_PUBLIC"},
    "BASEBALL":{"provider":"ESPN_PUBLIC"},
    "BASKETBALL":{"provider":"ESPN_PUBLIC"},
    "VOLLEYBALL":{"provider":"KOVO_OFFICIAL"},
}
LEAGUES={
    "SOCCER":[
        ("soccer","eng.1","Premier League"),
        ("soccer","esp.1","LaLiga"),
        ("soccer","ger.1","Bundesliga"),
        ("soccer","ita.1","Serie A"),
        ("soccer","fra.1","Ligue 1"),
        ("soccer","uefa.champions","UEFA Champions League"),
    ],
    "BASEBALL":[("baseball","mlb","MLB")],
    "BASKETBALL":[("basketball","nba","NBA")],
}

STATUS_BY_STATE={"pre":"SCHEDULED","in":"LIVE","post":"FINAL"}
STATUS_BY_NAME={
    "STATUS_SCHEDULED":"SCHEDULED","STATUS_IN_PROGRESS":"LIVE","STATUS_HALFTIME":"LIVE",
    "STATUS_FINAL":"FINAL","STATUS_FULL_TIME":"FINAL","STATUS_POSTPONED":"POSTPONED",
    "STATUS_CANCELED":"CANCELLED","STATUS_CANCELLED":"CANCELLED",
}

KOVO_TEAM_ALIASES={
    "대한항공":["대한항공","점보스"],
    "현대캐피탈":["현대캐피탈","스카이워커스"],
    "한국전력":["한국전력","빅스톰"],
    "삼성화재":["삼성화재","블루팡스"],
    "우리카드":["우리카드"],
    "KB손해보험":["KB손해보험","KB스타즈"],
    "OK저축은행":["OK저축은행","OK금융그룹","OK저축은행 읏맨"],
    "흥국생명":["흥국생명","핑크스파이더스"],
    "현대건설":["현대건설","힐스테이트"],
    "한국도로공사":["한국도로공사","하이패스"],
    "GS칼텍스":["GS칼텍스","서울KIXX","서울 Kixx"],
    "IBK기업은행":["IBK기업은행","알토스"],
    "정관장":["정관장","레드스파크스","KGC인삼공사"],
    "페퍼저축은행":["페퍼저축은행","AI페퍼스","페퍼스"],
}
_KOVO_CACHE={}

def _http_bytes(url:str,timeout:int=18,retries:int=2)->tuple[bytes,dict]:
    last=None
    for i in range(retries+1):
        try:
            req=urllib.request.Request(url,headers={
                "Accept":"text/html,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language":"ko-KR,ko;q=0.9,en;q=0.8",
                "Referer":"https://www.kovo.co.kr/",
                "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
            })
            with urllib.request.urlopen(req,timeout=timeout) as r:
                if r.status!=200: raise RuntimeError(f"HTTP_{r.status}")
                return r.read(), dict(r.headers.items())
        except Exception as e:
            last=e
            if i<retries: time.sleep(1+i)
    raise RuntimeError(f"FETCH_FAILED:{url}:{last!r}")

def _http_json(url:str,timeout:int=18,retries:int=2)->dict:
    raw,_=_http_bytes(url,timeout,retries)
    obj=json.loads(raw.decode("utf-8"))
    if not isinstance(obj,dict): raise RuntimeError("JSON_NOT_OBJECT")
    return obj

def _http_text(url:str,timeout:int=18,retries:int=2)->str:
    raw,headers=_http_bytes(url,timeout,retries)
    ctype=headers.get("Content-Type","")
    m=re.search(r"charset=([A-Za-z0-9_-]+)",ctype,re.I)
    encs=[m.group(1)] if m else []
    encs += ["utf-8","cp949","euc-kr"]
    seen=set()
    for enc in encs:
        if not enc or enc.lower() in seen: continue
        seen.add(enc.lower())
        try:return raw.decode(enc)
        except Exception:pass
    return raw.decode("utf-8","replace")

def _query_days(day:str)->list[str]:
    d=date.fromisoformat(day)
    return [(d-timedelta(days=1)).strftime("%Y%m%d"), d.strftime("%Y%m%d")]

def _league_url(sport_slug:str,league_slug:str,query_day:str)->str:
    return f"{ESPN_BASE}/{sport_slug}/{league_slug}/scoreboard?dates={query_day}"

def _parse_iso(s:str)->datetime:
    if s.endswith("Z"):s=s[:-1]+"+00:00"
    return datetime.fromisoformat(s).astimezone(KST)

def _competitors(ev:dict):
    comps=ev.get("competitions") or []
    if not comps:return None,None,None
    comp=comps[0] or {};home=away=None
    for x in comp.get("competitors") or []:
        if x.get("homeAway")=="home":home=x
        elif x.get("homeAway")=="away":away=x
    return comp,home,away

def _team_name(c:dict|None)->str:
    if not c:return ""
    t=c.get("team") or {}
    return str(t.get("displayName") or t.get("shortDisplayName") or t.get("name") or "")

def _num_score(c:dict|None):
    if not c:return None
    try:
        f=float(c.get("score"))
        return int(f) if f.is_integer() else f
    except Exception:return None

def _status(ev:dict,comp:dict)->str:
    t=(comp.get("status") or ev.get("status") or {}).get("type") or {}
    name=str(t.get("name") or "").upper();state=str(t.get("state") or "").lower()
    if name in STATUS_BY_NAME:return STATUS_BY_NAME[name]
    if state in STATUS_BY_STATE:return STATUS_BY_STATE[state]
    if t.get("completed") is True:return "FINAL"
    return "SCHEDULED"

def _winner_key(sport:str,home:dict|None,away:dict|None,hs,aas):
    if home and home.get("winner") is True:return "HOME"
    if away and away.get("winner") is True:return "AWAY"
    if hs is None or aas is None:return None
    if hs>aas:return "HOME"
    if aas>hs:return "AWAY"
    return "DRAW" if sport=="SOCCER" else None

def parse_event(sport:str,ev:dict,requested_day:str,league_name:str,source_url:str)->dict|None:
    ds=ev.get("date")
    if not ds:return None
    try:dt=_parse_iso(str(ds))
    except Exception:return None
    if dt.date().isoformat()!=requested_day:return None
    comp,home_c,away_c=_competitors(ev)
    if not comp or not home_c or not away_c:return None
    home=_team_name(home_c);away=_team_name(away_c)
    if not home or not away:return None
    eid=ev.get("id")
    if eid is None:return None
    status=_status(ev,comp);hs=_num_score(home_c);aas=_num_score(away_c)
    outcomes=[{"key":"HOME","name":home},{"key":"AWAY","name":away}]
    if sport=="SOCCER":outcomes.insert(1,{"key":"DRAW","name":"무승부"})
    out={
        "id":f"SPORTS-{sport}-{eid}","provider_event_id":str(eid),"domain":"SPORTS","sport":sport,
        "provider":"ESPN_PUBLIC","provider_kind":"PUBLIC_SCORE_FEED","competition":league_name,
        "event_date":requested_day,"start_time":dt.strftime("%H:%M"),"start_timestamp":int(dt.timestamp()),
        "status":status,"title":f"{home} vs {away}","home":home,"away":away,
        "market_type":"THREE_WAY" if sport=="SOCCER" else "TWO_WAY","outcomes":outcomes,
        "tier":"TOP","tier_filter":"CONFIGURED_TOP_TIER_LEAGUE","data_state":"FRESH","source_url":source_url,
    }
    if status=="FINAL" and hs is not None and aas is not None:
        out["result"]={"official":False,"status":"CONFIRMED","home_score":hs,"away_score":aas,
                       "winner_key":_winner_key(sport,home_c,away_c,hs,aas),
                       "source":"ESPN_PUBLIC","updated_at":datetime.now(KST).isoformat()}
    elif status=="LIVE" and hs is not None and aas is not None:
        out["score"]={"home":hs,"away":aas}
    return out

def _fetch_espn_day(sport:str,day:str)->tuple[list[dict],dict]:
    jobs=[]
    for sport_slug,league_slug,league_name in LEAGUES[sport]:
        for qd in _query_days(day):
            jobs.append((sport_slug,league_slug,league_name,_league_url(sport_slug,league_slug,qd)))
    all_events=[];sources=[];failures=[];success=0;raw_count=0
    def one(job):
        _,_,league_name,url=job
        obj=_http_json(url);raw=obj.get("events")
        if not isinstance(raw,list):raise RuntimeError("EVENTS_NOT_LIST")
        return league_name,url,raw
    with ThreadPoolExecutor(max_workers=min(6,len(jobs))) as ex:
        futs={ex.submit(one,j):j for j in jobs}
        for fut in as_completed(futs):
            j=futs[fut]
            try:
                league_name,url,raw=fut.result();success+=1;raw_count+=len(raw);sources.append(url)
                for ev in raw:
                    x=parse_event(sport,ev,day,league_name,url)
                    if x:all_events.append(x)
            except Exception as exc:
                failures.append({"league":j[2],"error":str(exc)[:250],"url":j[3]})
    if success==0:raise RuntimeError("ALL_LEAGUES_FAILED:"+json.dumps(failures,ensure_ascii=False))
    uniq={e["id"]:e for e in all_events};events=sorted(uniq.values(),key=lambda e:(e.get("start_timestamp",0),e["id"]))
    return events,{"sport":sport,"provider":"ESPN_PUBLIC","status":"PASS" if not failures else "PARTIAL",
                   "requests":len(jobs),"successful_requests":success,"raw_events":raw_count,
                   "top_tier_events":len(events),"source_urls":sources,"failures":failures}

class _Rows(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.in_tr=False;self.in_cell=False;self.cells=[];self.cell=[];self.links=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=="tr":
            self.in_tr=True;self.cells=[];self.links=[]
        elif self.in_tr and tag in ("td","th"):
            self.in_cell=True;self.cell=[]
        elif self.in_tr and tag=="img":
            alt=attrs.get("alt")
            if alt:self.cell.append(alt)
        elif self.in_tr and tag=="a":
            href=attrs.get("href")
            if href:self.links.append(href)
    def handle_data(self,data):
        if self.in_tr and self.in_cell:self.cell.append(data)
    def handle_endtag(self,tag):
        if self.in_tr and tag in ("td","th") and self.in_cell:
            txt=" ".join("".join(self.cell).replace("\xa0"," ").split())
            self.cells.append(txt);self.in_cell=False;self.cell=[]
        elif tag=="tr" and self.in_tr:
            if self.cells:self.rows.append((self.cells,list(self.links)))
            self.in_tr=False;self.cells=[];self.links=[]

def _kovo_season_for_day(d:date)->str:
    start_year=d.year if d.month>=7 else d.year-1
    return f"{start_year-2003:03d}"

def _kovo_month_urls(d:date)->list[str]:
    base=f"{KOVO_BASE}?season={_kovo_season_for_day(d)}&team=&yymm={d.strftime('%Y-%m')}&r_round="
    # Current KOVO pages are most reliable when men's/women's divisions are
    # requested explicitly. Merge both into one top-tier V-League feed.
    return [base+"&s_part=1", base+"&s_part=2"]

def _canonical_kovo_teams(text:str)->list[str]:
    found=[]
    for canon,aliases in KOVO_TEAM_ALIASES.items():
        pos=min([text.find(a) for a in aliases if a in text] or [-1])
        if pos>=0:found.append((pos,canon))
    found.sort()
    out=[]
    for _,x in found:
        if x not in out:out.append(x)
    return out

def _date_from_cells(cells:list[str],month_date:date,current:date|None)->date|None:
    joined=" ".join(cells)
    m=re.search(r"(20\d{2})[./-]\s*(\d{1,2})[./-]\s*(\d{1,2})",joined)
    if m:
        try:return date(int(m.group(1)),int(m.group(2)),int(m.group(3)))
        except Exception:pass
    m=re.search(r"(?<!\d)(\d{1,2})[./-]\s*(\d{1,2})(?!\d)",joined)
    if m:
        mo,da=int(m.group(1)),int(m.group(2))
        try:
            y=month_date.year
            if mo==12 and month_date.month==1:y-=1
            elif mo==1 and month_date.month==12:y+=1
            return date(y,mo,da)
        except Exception:pass
    return current

def _score_from_cells(cells:list[str]):
    for cell in cells:
        if re.fullmatch(r"\s*[0-3]\s*[:\-]\s*[0-3]\s*",cell):
            a,b=re.split(r"[:\-]",cell)
            return int(a.strip()),int(b.strip())
    return None,None

def _time_from_cells(cells:list[str])->str:
    for cell in cells:
        m=re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)",cell)
        if m:return f"{int(m.group(1)):02d}:{m.group(2)}"
    return "19:00"

def _parse_kovo_month(html:str,month_date:date,source_url:str)->list[dict]:
    p=_Rows();p.feed(html);rows=[];current=None
    for cells,links in p.rows:
        current=_date_from_cells(cells,month_date,current)
        if current is None:continue
        joined=" | ".join(cells)
        teams=_canonical_kovo_teams(joined)
        if len(teams)<2:continue
        home,away=teams[0],teams[1]
        tm=_time_from_cells(cells)
        try:
            dt=datetime.combine(current,datetime.strptime(tm,"%H:%M").time(),tzinfo=KST)
        except Exception:continue
        hs,aas=_score_from_cells(cells)
        final=hs is not None and aas is not None
        now=datetime.now(KST)
        if final:status="FINAL"
        elif current<now.date():status="RESULT_PENDING"
        elif current>now.date():status="SCHEDULED"
        elif now<dt:status="SCHEDULED"
        elif now<=dt+timedelta(hours=3):status="LIVE"
        else:status="RESULT_PENDING"
        identity=f"{current.isoformat()}|{tm}|{home}|{away}"
        eid=hashlib.sha1(identity.encode("utf-8")).hexdigest()[:14]
        out={
            "id":f"SPORTS-VOLLEYBALL-KOVO-{eid}","provider_event_id":eid,"domain":"SPORTS","sport":"VOLLEYBALL",
            "provider":"KOVO_OFFICIAL","provider_kind":"OFFICIAL_LEAGUE_SITE","competition":"KOVO V-League",
            "event_date":current.isoformat(),"start_time":tm,"start_timestamp":int(dt.timestamp()),"status":status,
            "title":f"{home} vs {away}","home":home,"away":away,"market_type":"TWO_WAY",
            "outcomes":[{"key":"HOME","name":home},{"key":"AWAY","name":away}],
            "tier":"TOP","tier_filter":"KOVO_V_LEAGUE_TOP_DIVISION","data_state":"FRESH","source_url":source_url,
        }
        if final:
            out["result"]={"official":True,"status":"CONFIRMED","home_score":hs,"away_score":aas,
                           "winner_key":"HOME" if hs>aas else "AWAY" if aas>hs else None,
                           "source":"KOVO_OFFICIAL","updated_at":datetime.now(KST).isoformat()}
        rows.append(out)
    uniq={e["id"]:e for e in rows}
    return sorted(uniq.values(),key=lambda e:(e["start_timestamp"],e["id"]))

def _fetch_kovo_day(day:str)->tuple[list[dict],dict]:
    d=date.fromisoformat(day);key=d.strftime("%Y-%m")
    if key not in _KOVO_CACHE:
        merged=[];urls=[];failures=[];html_bytes=0;success=0
        for url in _kovo_month_urls(d):
            try:
                html=_http_text(url);html_bytes+=len(html);success+=1;urls.append(url)
                merged.extend(_parse_kovo_month(html,d,url))
            except Exception as exc:
                failures.append({"url":url,"error":str(exc)[:250]})
        if success==0:
            raise RuntimeError("KOVO_ALL_DIVISIONS_FAILED:"+json.dumps(failures,ensure_ascii=False))
        uniq={e["id"]:e for e in merged}
        parsed=sorted(uniq.values(),key=lambda e:(e["start_timestamp"],e["id"]))
        _KOVO_CACHE[key]=(parsed,urls,html_bytes,success,failures)
    parsed,urls,html_len,success,failures=_KOVO_CACHE[key]
    events=[e for e in parsed if e.get("event_date")==day]
    return events,{"sport":"VOLLEYBALL","provider":"KOVO_OFFICIAL",
                   "status":"PASS" if not failures else "PARTIAL","requests":2,
                   "successful_requests":success,"raw_events":len(parsed),
                   "top_tier_events":len(events),"source_urls":urls,
                   "html_bytes":html_len,"failures":failures}

def fetch_sport_day(sport:str,day:str)->tuple[list[dict],dict]:
    if sport=="VOLLEYBALL":return _fetch_kovo_day(day)
    if sport in LEAGUES:return _fetch_espn_day(sport,day)
    raise KeyError(sport)

def _fixture(sport:str)->dict:
    return {"id":"401234567","date":"2026-10-04T03:00:00Z","competitions":[{
        "status":{"type":{"name":"STATUS_FINAL","state":"post","completed":True}},
        "competitors":[
            {"homeAway":"home","winner":True,"score":"2","team":{"displayName":"Home FC"}},
            {"homeAway":"away","winner":False,"score":"1","team":{"displayName":"Away FC"}},
        ]}]}

def self_test():
    for sport in ("SOCCER","BASEBALL","BASKETBALL"):
        x=parse_event(sport,_fixture(sport),"2026-10-04","TEST TOP","https://example.test")
        assert x and x["status"]=="FINAL" and x["result"]["winner_key"]=="HOME"
    html="""<table><tr><td>2026.10.04</td><td>1</td><td>대한항공</td><td>현대캐피탈</td><td>14:00</td><td>3 : 1</td></tr></table>"""
    rows=_parse_kovo_month(html,date(2026,10,1),"https://example.test")
    assert len(rows)==1 and rows[0]["provider"]=="KOVO_OFFICIAL" and rows[0]["result"]["winner_key"]=="HOME"
    print(json.dumps({"SPORTS_PROVIDER_SELF_TEST":"PASS","providers":{"SOCCER":"ESPN_PUBLIC","BASEBALL":"ESPN_PUBLIC","BASKETBALL":"ESPN_PUBLIC","VOLLEYBALL":"KOVO_OFFICIAL"}},ensure_ascii=False))

def live_probe(day:str|None=None):
    day=day or datetime.now(KST).date().isoformat();rows={}
    for sport in SPORTS:
        events,meta=fetch_sport_day(sport,day);rows[sport]=meta
    print(json.dumps({"SPORTS_PROVIDER_LIVE_PROBE":"PASS","date":day,"providers":rows},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");ap.add_argument("--live-probe",action="store_true");ap.add_argument("--date");a=ap.parse_args()
    if a.self_test:return self_test()
    return live_probe(a.date)
if __name__=="__main__":main()
