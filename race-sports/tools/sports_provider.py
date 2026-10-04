#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math, re, time, urllib.request, http.cookiejar
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timezone, timedelta
from html.parser import HTMLParser
from typing import Any

KST=timezone(timedelta(hours=9))
ESPN_BASE="https://site.api.espn.com/apis/site/v2/sports"
KOVO_BASE="https://www.kovo.co.kr/game/v-league/11110_schedule_list.asp"
KOVO_MOBILE_BASE="https://m.kovo.co.kr/game/v-league/11110_schedule_list.asp"
KBO_GAMES_URL="https://www.koreabaseball.com/ws/Main.asmx/GetKboGameList"
KBL_MATCH_URL="https://api.kbl.or.kr/match/list"
KLEAGUE_SCHEDULE_URL="https://www.kleague.com/getScheduleList.do"

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
        ("soccer","uefa.nations","UEFA Nations League"),
        ("soccer","fifa.friendly","International Friendly"),
        ("soccer","afc.asian.cup","AFC Asian Cup"),
        ("soccer","afc.champions","AFC Champions League Elite"),
        ("soccer","afc.cup","AFC Champions League Two"),
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
    "SOOP":["SOOP"],
}
_KOVO_CACHE={}
_KOVO_OPENERS={}

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

def _json_request(url:str,method:str="GET",body:dict|None=None,headers:dict|None=None,timeout:int=18,retries:int=2):
    data=None
    h={
        "Accept":"application/json, text/plain, */*",
        "Accept-Language":"ko-KR,ko;q=.9,en;q=.7",
        "User-Agent":"Mozilla/5.0 (RACEIQ/1.0)",
    }
    if body is not None:
        data=json.dumps(body,ensure_ascii=False).encode("utf-8")
        h["Content-Type"]="application/json; charset=utf-8"
    if headers:h.update(headers)
    last=None
    for i in range(retries+1):
        try:
            req=urllib.request.Request(url,data=data,headers=h,method=method)
            with urllib.request.urlopen(req,timeout=timeout) as r:
                raw=r.read()
                txt=raw.decode("utf-8","replace")
                try:
                    return json.loads(txt)
                except json.JSONDecodeError:
                    # KBO ASP.NET occasionally appends an error document after
                    # a valid JSON object. Keep only the verified JSON prefix.
                    cut=txt.find("}<!")
                    if cut>0:
                        return json.loads(txt[:cut+1])
                    raise
        except Exception as exc:
            last=exc
            if i<retries:time.sleep(1+i)
    raise RuntimeError(f"JSON_REQUEST_FAILED:{url}:{last!r}")

def _decode_html(raw:bytes,headers:dict)->str:
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

def _http_text(url:str,timeout:int=18,retries:int=2)->str:
    raw,headers=_http_bytes(url,timeout,retries)
    return _decode_html(raw,headers)

def _kovo_session_text(url:str,timeout:int=18,retries:int=2)->str:
    mobile="://m.kovo.co.kr/" in url
    origin="https://m.kovo.co.kr/" if mobile else "https://www.kovo.co.kr/"
    opener=_KOVO_OPENERS.get(origin)
    if opener is None:
        jar=http.cookiejar.CookieJar()
        opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        _KOVO_OPENERS[origin]=opener
        try:
            req=urllib.request.Request(origin,headers={
                "Accept":"text/html,*/*;q=0.8",
                "Accept-Language":"ko-KR,ko;q=0.9,en;q=0.8",
                "User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148" if mobile else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
            })
            with opener.open(req,timeout=timeout) as r:r.read()
        except Exception:
            pass
    last=None
    for i in range(retries+1):
        try:
            req=urllib.request.Request(url,headers={
                "Accept":"text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language":"ko-KR,ko;q=0.9,en;q=0.8",
                "Referer":origin,
                "User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148" if mobile else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
            })
            with opener.open(req,timeout=timeout) as r:
                if r.status!=200:raise RuntimeError(f"HTTP_{r.status}")
                raw=r.read();headers=dict(r.headers.items())
                return _decode_html(raw,headers)
        except Exception as exc:
            last=exc
            if i<retries:time.sleep(1+i)
    raise RuntimeError(f"KOVO_FETCH_FAILED:{url}:{last!r}")

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

def _american_to_decimal(v):
    try:
        if isinstance(v,str):
            t=v.strip().upper()
            if t in {"EVEN","EV","PK","PICK"}:return 2.0
            v=float(t.replace("+",""))
        else:v=float(v)
        if not math.isfinite(v) or v==0:return None
        return round(1.0+v/100.0,4) if v>0 else round(1.0+100.0/abs(v),4)
    except Exception:return None

def _moneyline_value(x):
    if x is None:return None
    if isinstance(x,(int,float,str)):return _american_to_decimal(x)
    if isinstance(x,dict):
        for k in ("moneyLine","moneyline","money_line","current","value","close"):
            if k in x:
                d=_moneyline_value(x.get(k))
                if d:return d
    return None

def _extract_espn_moneyline(container:dict)->tuple[dict,str]:
    rows=[]
    for key in ("odds","pickcenter"):
        v=container.get(key)
        if isinstance(v,list):rows.extend(x for x in v if isinstance(x,dict))
        elif isinstance(v,dict):rows.append(v)
    for row in rows:
        home=_moneyline_value(row.get("homeTeamOdds") or row.get("homeOdds"))
        away=_moneyline_value(row.get("awayTeamOdds") or row.get("awayOdds"))
        draw=_moneyline_value(row.get("drawOdds"))
        if not (home and away):continue
        pr=row.get("provider") or {}
        provider=str(pr.get("name") or pr.get("displayName") or row.get("providerName") or "ESPN listed market")
        out={"HOME":home,"AWAY":away}
        if draw:out["DRAW"]=draw
        return out,provider
    return {},""

def _apply_espn_odds(out:dict,container:dict)->bool:
    odds,provider=_extract_espn_moneyline(container)
    if not odds:return False
    now=datetime.now(KST).isoformat()
    applied=0
    for o in out.get("outcomes",[]):
        d=odds.get(o.get("key"))
        if not d:continue
        o["odds"]=d
        o["odds_source"]="ESPN_PUBLIC_ODDS"
        o["odds_provider"]=provider
        o["odds_capture_mode"]="PRE_GAME_SOURCE_LABELED"
        o["odds_updated_at"]=now
        applied+=1
    if applied>=2:
        out["odds_source"]="ESPN_PUBLIC_ODDS"
        out["odds_provider"]=provider
        out["odds_state"]="SOURCE_LABELED_MARKET"
        return True
    return False

def _summary_url(sport_slug:str,league_slug:str,event_id:str)->str:
    return f"{ESPN_BASE}/{sport_slug}/{league_slug}/summary?event={event_id}"

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
    _apply_espn_odds(out,comp)
    _apply_espn_odds(out,ev)
    return out

def _fetch_espn_day(sport:str,day:str,include_odds:bool=False)->tuple[list[dict],dict]:
    jobs=[]
    for sport_slug,league_slug,league_name in LEAGUES[sport]:
        for qd in _query_days(day):
            jobs.append((sport_slug,league_slug,league_name,_league_url(sport_slug,league_slug,qd)))
    all_events=[];sources=[];failures=[];success=0;raw_count=0
    def one(job):
        sport_slug,league_slug,league_name,url=job
        obj=_http_json(url);raw=obj.get("events")
        if not isinstance(raw,list):raise RuntimeError("EVENTS_NOT_LIST")
        return sport_slug,league_slug,league_name,url,raw
    with ThreadPoolExecutor(max_workers=min(6,len(jobs))) as ex:
        futs={ex.submit(one,j):j for j in jobs}
        for fut in as_completed(futs):
            j=futs[fut]
            try:
                sport_slug,league_slug,league_name,url,raw=fut.result()
                success+=1;raw_count+=len(raw);sources.append(url)
                for ev in raw:
                    x=parse_event(sport,ev,day,league_name,url)
                    if x:
                        x["_espn_sport_slug"]=sport_slug;x["_espn_league_slug"]=league_slug
                        all_events.append(x)
            except Exception as exc:
                failures.append({"league":j[2],"error":str(exc)[:250],"url":j[3]})
    if success==0:raise RuntimeError("ALL_LEAGUES_FAILED:"+json.dumps(failures,ensure_ascii=False))
    uniq={e["id"]:e for e in all_events}
    events=sorted(uniq.values(),key=lambda e:(e.get("start_timestamp",0),e["id"]))

    odds_requests=0;odds_success=0
    if include_odds:
        targets=[e for e in events if not any(o.get("odds") for o in e.get("outcomes",[]))]
        def odds_one(e):
            url=_summary_url(e["_espn_sport_slug"],e["_espn_league_slug"],e["provider_event_id"])
            return e["id"],url,_http_json(url)
        if targets:
            with ThreadPoolExecutor(max_workers=min(6,len(targets))) as ex:
                futs={ex.submit(odds_one,e):e for e in targets}
                for fut in as_completed(futs):
                    odds_requests+=1
                    try:
                        eid,url,obj=fut.result()
                        e=next((x for x in events if x["id"]==eid),None)
                        if e and _apply_espn_odds(e,obj):
                            odds_success+=1
                            e["odds_source_url"]=url
                    except Exception as exc:
                        e=futs[fut]
                        failures.append({"league":e.get("competition"),"error":"ODDS_SUMMARY:"+str(exc)[:200],"url":_summary_url(e["_espn_sport_slug"],e["_espn_league_slug"],e["provider_event_id"])})
    for e in events:
        e.pop("_espn_sport_slug",None);e.pop("_espn_league_slug",None)
    odds_events=sum(1 for e in events if sum(1 for o in e.get("outcomes",[]) if isinstance(o.get("odds"),(int,float)) and float(o.get("odds"))>1)>=2)
    return events,{"sport":sport,"provider":"ESPN_PUBLIC","status":"PASS" if not failures else "PARTIAL",
                   "requests":len(jobs)+odds_requests,"successful_requests":success+odds_success,"raw_events":raw_count,
                   "top_tier_events":len(events),"odds_events":odds_events,"odds_summary_requests":odds_requests,
                   "source_urls":sources,"failures":failures}

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
    season=_kovo_season_for_day(d);ym=d.strftime('%Y-%m')
    desktop=f"{KOVO_BASE}?season={season}&team=&yymm={ym}&r_round="
    return [desktop+"&s_part=1",desktop+"&s_part=2"]

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

def _daum_volley_url(slug:str,d:date)->str:
    return f"https://sports.daum.net/schedule/{slug}?date={d.strftime('%Y%m')}"

def _parse_daum_volley_month(html:str,month_date:date,source_url:str,league_name:str)->list[dict]:
    p=_Rows();p.feed(html);rows=[];current=None
    for cells,links in p.rows:
        current=_date_from_cells(cells,month_date,current)
        if current is None:continue
        joined=" | ".join(cells)
        teams=_canonical_kovo_teams(joined)
        if len(teams)<2:continue
        home,away=teams[0],teams[1]
        tm=_time_from_cells(cells)
        try:dt=datetime.combine(current,datetime.strptime(tm,"%H:%M").time(),tzinfo=KST)
        except Exception:continue
        score_tokens=[int(x) for x in re.findall(r"(?:팀|score[^0-9]*)\s*([0-3])",joined,re.I)]
        if len(score_tokens)<2:
            compact=re.findall(r"(?<!\d)([0-3])\s*(?:대|:)\s*([0-3])(?!\d)",joined)
            if compact:score_tokens=[int(compact[0][0]),int(compact[0][1])]
        final="종료" in joined and len(score_tokens)>=2
        cancelled="취소" in joined
        now=datetime.now(KST)
        if cancelled:status="CANCELLED"
        elif final:status="FINAL"
        elif current<now.date():status="RESULT_PENDING"
        elif current>now.date() or now<dt:status="SCHEDULED"
        elif now<=dt+timedelta(hours=3):status="LIVE"
        else:status="RESULT_PENDING"
        identity=f"DAUM|{league_name}|{current.isoformat()}|{tm}|{home}|{away}"
        eid=hashlib.sha1(identity.encode("utf-8")).hexdigest()[:14]
        out={
            "id":f"SPORTS-VOLLEYBALL-DAUM-{eid}","provider_event_id":eid,
            "domain":"SPORTS","sport":"VOLLEYBALL",
            "provider":"DAUM_SPORTS_PUBLIC_FALLBACK","provider_kind":"PUBLIC_SCORE_FEED",
            "competition":league_name,"event_date":current.isoformat(),"start_time":tm,
            "start_timestamp":int(dt.timestamp()),"status":status,
            "title":f"{home} vs {away}","home":home,"away":away,
            "market_type":"TWO_WAY","outcomes":[{"key":"HOME","name":home},{"key":"AWAY","name":away}],
            "tier":"TOP","tier_filter":"KOVO_V_LEAGUE_TOP_DIVISION",
            "data_state":"FRESH","source_url":source_url,
        }
        if final:
            hs,aas=score_tokens[0],score_tokens[1]
            out["result"]={
                "official":False,"status":"CONFIRMED","home_score":hs,"away_score":aas,
                "score_type":"SETS","winner_key":"HOME" if hs>aas else "AWAY" if aas>hs else None,
                "source":"DAUM_SPORTS_PUBLIC_FALLBACK","updated_at":datetime.now(KST).isoformat()
            }
        rows.append(out)
    uniq={e["id"]:e for e in rows}
    return sorted(uniq.values(),key=lambda e:(e["start_timestamp"],e["id"]))

def _fetch_daum_volleyball_day(day:str)->tuple[list[dict],dict]:
    d=date.fromisoformat(day);all_events=[];urls=[];failures=[];success=0;raw_count=0
    for slug,league in (("vl","KOVO V-League Men"),("wvl","KOVO V-League Women")):
        url=_daum_volley_url(slug,d)
        try:
            html=_http_text(url);success+=1;urls.append(url)
            parsed=_parse_daum_volley_month(html,d,url,league);raw_count+=len(parsed)
            all_events.extend(e for e in parsed if e.get("event_date")==day)
        except Exception as exc:
            failures.append({"url":url,"error":str(exc)[:250]})
    if success==0:raise RuntimeError("DAUM_VOLLEY_ALL_FAILED:"+json.dumps(failures,ensure_ascii=False))
    uniq={e["id"]:e for e in all_events}
    events=sorted(uniq.values(),key=lambda e:(e["start_timestamp"],e["id"]))
    return events,{
        "sport":"VOLLEYBALL","provider":"DAUM_SPORTS_PUBLIC_FALLBACK",
        "status":"PASS" if not failures else "PARTIAL","requests":2,
        "successful_requests":success,"raw_events":raw_count,"top_tier_events":len(events),
        "source_urls":urls,"failures":failures,
    }

def _fetch_kovo_day(day:str)->tuple[list[dict],dict]:
    d=date.fromisoformat(day);key=d.strftime("%Y-%m")
    if key not in _KOVO_CACHE:
        merged=[];urls=[];failures=[];html_bytes=0;success=0
        for url in _kovo_month_urls(d):
            try:
                html=_kovo_session_text(url);html_bytes+=len(html);success+=1;urls.append(url)
                merged.extend(_parse_kovo_month(html,d,url))
            except Exception as exc:
                failures.append({"url":url,"error":str(exc)[:250]})
        uniq={e["id"]:e for e in merged}
        parsed=sorted(uniq.values(),key=lambda e:(e["start_timestamp"],e["id"]))
        _KOVO_CACHE[key]=(parsed,urls,html_bytes,success,failures)
    parsed,urls,html_len,success,failures=_KOVO_CACHE[key]
    events=[e for e in parsed if e.get("event_date")==day]
    if events:
        return events,{"sport":"VOLLEYBALL","provider":"KOVO_OFFICIAL",
                       "status":"PASS" if success else "PARTIAL","requests":len(_kovo_month_urls(d)),
                       "successful_requests":success,"raw_events":len(parsed),
                       "top_tier_events":len(events),"source_urls":urls,
                       "html_bytes":html_len,"failures":failures}
    # The legacy KOVO schedule route can return a shell page after the site's
    # redesign. Use a source-labeled public scoreboard only for schedule/live
    # continuity. Historical training remains official KOVO DBBank only.
    daum_events,meta=_fetch_daum_volleyball_day(day)
    meta["primary_provider"]="KOVO_OFFICIAL"
    meta["primary_successful_requests"]=success
    meta["primary_raw_events"]=len(parsed)
    meta["primary_source_urls"]=urls
    meta["historical_training_source"]="KOVO_DBBANK_OFFICIAL_ONLY"
    return daum_events,meta

KBO_STATUS={"1":"SCHEDULED","2":"LIVE","3":"FINAL"}
KBO_TEAM_KO={"LG":"LG","OB":"두산","KT":"KT","SK":"SSG","NC":"NC","HT":"KIA","LT":"롯데","SS":"삼성","HH":"한화","WO":"키움"}

def _kbo_status(raw:dict)->str:
    cancel=str(raw.get("CANCEL_SC_ID") or "").strip()
    if cancel and cancel!="0":return "CANCELLED"
    return KBO_STATUS.get(str(raw.get("GAME_STATE_SC") or "1"),"SCHEDULED")

def _fetch_kbo_day(day:str)->tuple[list[dict],dict]:
    compact=day.replace("-","")
    obj=_json_request(KBO_GAMES_URL,"POST",{"leId":"1","srId":"0,1,3,4,5,7,9","date":compact},headers={
        "X-Requested-With":"XMLHttpRequest",
        "Referer":"https://www.koreabaseball.com/Schedule/ScoreBoard.aspx",
    },timeout=15,retries=1)
    rows=obj.get("game")
    if not isinstance(rows,list):raise RuntimeError("KBO_GAME_LIST_NOT_ARRAY")
    out=[]
    for r in rows:
        if not isinstance(r,dict):continue
        gid=str(r.get("G_ID") or "").strip()
        gdt=str(r.get("G_DT") or "").strip()
        away=str(r.get("AWAY_NM") or KBO_TEAM_KO.get(str(r.get("AWAY_ID") or ""),"")).strip()
        home=str(r.get("HOME_NM") or KBO_TEAM_KO.get(str(r.get("HOME_ID") or ""),"")).strip()
        tm=str(r.get("G_TM") or "").strip()
        if len(tm)==4 and tm.isdigit():tm=tm[:2]+":"+tm[2:]
        if not gid or not away or not home:continue
        status=_kbo_status(r)
        try:dt=datetime.strptime(day+" "+tm,"%Y-%m-%d %H:%M").replace(tzinfo=KST)
        except Exception:dt=datetime.fromisoformat(day+"T14:00:00+09:00")
        e={
            "id":f"SPORTS-BASEBALL-KBO-{gid}","provider_event_id":gid,"domain":"SPORTS","sport":"BASEBALL",
            "provider":"KBO_OFFICIAL","provider_kind":"OFFICIAL_JSON_API","competition":"KBO",
            "event_date":day,"start_time":tm or "--:--","start_timestamp":int(dt.timestamp()),
            "status":status,"title":f"{home} vs {away}","home":home,"away":away,
            "market_type":"TWO_WAY","outcomes":[{"key":"HOME","name":home},{"key":"AWAY","name":away}],
            "tier":"TOP","tier_filter":"KBO_FIRST_TEAM","data_state":"FRESH","source_url":"https://www.koreabaseball.com/Schedule/ScoreBoard.aspx",
            "venue":r.get("S_NM"),
        }
        if status in {"LIVE","FINAL"}:
            try:hs=int(r.get("B_SCORE_CN"));aas=int(r.get("T_SCORE_CN"))
            except Exception:hs=aas=None
            if hs is not None and aas is not None:
                if status=="LIVE":e["score"]={"home":hs,"away":aas}
                else:e["result"]={"official":True,"status":"CONFIRMED","home_score":hs,"away_score":aas,"winner_key":"HOME" if hs>aas else "AWAY" if aas>hs else None,"source":"KBO_OFFICIAL","updated_at":datetime.now(KST).isoformat()}
        out.append(e)
    return out,{"sport":"BASEBALL","provider":"KBO_OFFICIAL","status":"PASS","requests":1,"successful_requests":1,"raw_events":len(rows),"top_tier_events":len(out),"failures":[]}

def _fetch_kbl_day(day:str)->tuple[list[dict],dict]:
    compact=day.replace("-","")
    url=f"{KBL_MATCH_URL}?fromDate={compact}&toDate={compact}&tcodeList=all&seasonGrade=1"
    obj=_json_request(url,headers={"X-Requested-With":"XMLHttpRequest","channel":"WEB","teamcode":"XX","lang":"ko"},timeout=15,retries=1)
    if not isinstance(obj,list):raise RuntimeError("KBL_MATCH_LIST_NOT_ARRAY")
    out=[]
    for r in obj:
        if not isinstance(r,dict) or str(r.get("gameDate") or "")!=compact:continue
        home=str(r.get("tnameH") or r.get("tnameFH") or "").strip()
        away=str(r.get("tnameA") or r.get("tnameFA") or "").strip()
        if not home or not away:continue
        tm=str(r.get("gameStart") or "").strip()
        if len(tm)==4 and tm.isdigit():tm=tm[:2]+":"+tm[2:]
        status="FINAL" if int(r.get("isEnded") or 0)==1 else "LIVE" if int(r.get("isStarted") or 0)==1 else "SCHEDULED"
        try:dt=datetime.strptime(day+" "+tm,"%Y-%m-%d %H:%M").replace(tzinfo=KST)
        except Exception:dt=datetime.fromisoformat(day+"T14:00:00+09:00")
        gid=str(r.get("gmkey") or r.get("gameCode") or r.get("gameNo") or hashlib.sha1((home+away+day+tm).encode()).hexdigest()[:12])
        e={
            "id":f"SPORTS-BASKETBALL-KBL-{gid}","provider_event_id":gid,"domain":"SPORTS","sport":"BASKETBALL",
            "provider":"KBL_OFFICIAL","provider_kind":"OFFICIAL_JSON_API","competition":"KBL",
            "event_date":day,"start_time":tm or "--:--","start_timestamp":int(dt.timestamp()),"status":status,
            "title":f"{home} vs {away}","home":home,"away":away,"market_type":"TWO_WAY",
            "outcomes":[{"key":"HOME","name":home},{"key":"AWAY","name":away}],
            "tier":"TOP","tier_filter":"KBL_SEASON_GRADE_1","data_state":"FRESH","source_url":url,
            "venue":r.get("stadiumnameF") or r.get("stadiumname"),
        }
        if status in {"LIVE","FINAL"}:
            try:hs=int(r.get("scoreH"));aas=int(r.get("scoreA"))
            except Exception:hs=aas=None
            if hs is not None and aas is not None:
                if status=="LIVE":e["score"]={"home":hs,"away":aas}
                else:e["result"]={"official":True,"status":"CONFIRMED","home_score":hs,"away_score":aas,"winner_key":"HOME" if hs>aas else "AWAY" if aas>hs else None,"source":"KBL_OFFICIAL","updated_at":datetime.now(KST).isoformat()}
        out.append(e)
    return out,{"sport":"BASKETBALL","provider":"KBL_OFFICIAL","status":"PASS","requests":1,"successful_requests":1,"raw_events":len(obj),"top_tier_events":len(out),"failures":[]}

def _fetch_kleague1_day(day:str)->tuple[list[dict],dict]:
    d=date.fromisoformat(day)
    obj=_json_request(KLEAGUE_SCHEDULE_URL,"POST",{"year":str(d.year),"month":f"{d.month:02d}","leagueId":1},headers={
        "Referer":"https://www.kleague.com/schedule.do?leagueId=1",
    },timeout=15,retries=1)
    data=obj.get("data") if isinstance(obj,dict) else None
    if not isinstance(data,dict):data=obj if isinstance(obj,dict) else {}
    rows=data.get("scheduleList")
    if not isinstance(rows,list):raise RuntimeError("KLEAGUE_SCHEDULE_NOT_ARRAY")
    dotted=day.replace("-",".");out=[]
    for r in rows:
        if not isinstance(r,dict) or str(r.get("gameDate") or "")!=dotted:continue
        home=str(r.get("homeTeamName") or "").strip();away=str(r.get("awayTeamName") or "").strip()
        if not home or not away:continue
        tm=str(r.get("gameTime") or "").strip() or "--:--"
        code=str(r.get("gameStatus") or ("FE" if r.get("endYn")=="Y" else "NS"))
        status={"FE":"FINAL","NS":"SCHEDULED","LIVE":"LIVE","IN":"LIVE","HT":"LIVE","PP":"POSTPONED","CAN":"CANCELLED"}.get(code,"SCHEDULED")
        try:dt=datetime.strptime(day+" "+tm,"%Y-%m-%d %H:%M").replace(tzinfo=KST)
        except Exception:dt=datetime.fromisoformat(day+"T14:00:00+09:00")
        gid=str(r.get("gameId") or hashlib.sha1((home+away+day+tm).encode()).hexdigest()[:12])
        e={
            "id":f"SPORTS-SOCCER-KLEAGUE1-{gid}","provider_event_id":gid,"domain":"SPORTS","sport":"SOCCER",
            "provider":"KLEAGUE_OFFICIAL","provider_kind":"OFFICIAL_JSON_API","competition":"K League 1",
            "event_date":day,"start_time":tm,"start_timestamp":int(dt.timestamp()),"status":status,
            "title":f"{home} vs {away}","home":home,"away":away,"market_type":"THREE_WAY",
            "outcomes":[{"key":"HOME","name":home},{"key":"DRAW","name":"무승부"},{"key":"AWAY","name":away}],
            "tier":"TOP","tier_filter":"K_LEAGUE_1","data_state":"FRESH","source_url":KLEAGUE_SCHEDULE_URL,
            "venue":r.get("fieldNameFull") or r.get("fieldName"),
        }
        if status in {"LIVE","FINAL"}:
            try:hs=int(r.get("homeGoal"));aas=int(r.get("awayGoal"))
            except Exception:hs=aas=None
            if hs is not None and aas is not None:
                if status=="LIVE":e["score"]={"home":hs,"away":aas}
                else:e["result"]={"official":True,"status":"CONFIRMED","home_score":hs,"away_score":aas,"winner_key":"HOME" if hs>aas else "AWAY" if aas>hs else "DRAW","source":"KLEAGUE_OFFICIAL","updated_at":datetime.now(KST).isoformat()}
        out.append(e)
    return out,{"sport":"SOCCER","provider":"KLEAGUE_OFFICIAL","status":"PASS","requests":1,"successful_requests":1,"raw_events":len(rows),"top_tier_events":len(out),"failures":[]}

def _combine(primary:tuple[list[dict],dict],secondary:tuple[list[dict],dict],provider_name:str):
    a,ma=primary;b,mb=secondary
    uniq={e["id"]:e for e in [*a,*b]}
    rows=sorted(uniq.values(),key=lambda e:(e.get("start_timestamp",0),e.get("id","")))
    return rows,{
        "sport":ma.get("sport") or mb.get("sport"),"provider":provider_name,
        "status":"PASS" if ma.get("status")=="PASS" or mb.get("status")=="PASS" else "PARTIAL",
        "requests":int(ma.get("requests",0))+int(mb.get("requests",0)),
        "successful_requests":int(ma.get("successful_requests",0))+int(mb.get("successful_requests",0)),
        "raw_events":int(ma.get("raw_events",0))+int(mb.get("raw_events",0)),
        "top_tier_events":len(rows),
        "odds_events":int(ma.get("odds_events",0))+int(mb.get("odds_events",0)),
        "odds_summary_requests":int(ma.get("odds_summary_requests",0))+int(mb.get("odds_summary_requests",0)),
        "failures":[*(ma.get("failures") or []),*(mb.get("failures") or [])],
        "sources":[ma,mb],
    }

def fetch_sport_day(sport:str,day:str,include_odds:bool=False)->tuple[list[dict],dict]:
    if sport=="VOLLEYBALL":return _fetch_kovo_day(day)
    if sport=="BASEBALL":
        espn=_fetch_espn_day(sport,day,include_odds=include_odds)
        try:kbo=_fetch_kbo_day(day)
        except Exception as exc:kbo=([],{"sport":"BASEBALL","provider":"KBO_OFFICIAL","status":"FAIL","requests":1,"successful_requests":0,"raw_events":0,"top_tier_events":0,"failures":[{"error":str(exc)[:250]}]})
        return _combine(espn,kbo,"ESPN_PUBLIC+KBO_OFFICIAL")
    if sport=="BASKETBALL":
        espn=_fetch_espn_day(sport,day,include_odds=include_odds)
        try:kbl=_fetch_kbl_day(day)
        except Exception as exc:kbl=([],{"sport":"BASKETBALL","provider":"KBL_OFFICIAL","status":"FAIL","requests":1,"successful_requests":0,"raw_events":0,"top_tier_events":0,"failures":[{"error":str(exc)[:250]}]})
        return _combine(espn,kbl,"ESPN_PUBLIC+KBL_OFFICIAL")
    if sport=="SOCCER":
        espn=_fetch_espn_day(sport,day,include_odds=include_odds)
        try:kl=_fetch_kleague1_day(day)
        except Exception as exc:kl=([],{"sport":"SOCCER","provider":"KLEAGUE_OFFICIAL","status":"FAIL","requests":1,"successful_requests":0,"raw_events":0,"top_tier_events":0,"failures":[{"error":str(exc)[:250]}]})
        return _combine(espn,kl,"ESPN_PUBLIC+KLEAGUE_OFFICIAL")
    if sport in LEAGUES:return _fetch_espn_day(sport,day,include_odds=include_odds)
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
    dh="""<table><tr><td>02.01 수</td><td>19:00</td><td>화성종합</td><td>종료 페퍼저축은행 팀 1 IBK기업은행 팀 3</td><td>V-리그 여자부</td></tr></table>"""
    dr=_parse_daum_volley_month(dh,date(2023,2,1),"https://example.test","KOVO V-League Women")
    assert len(dr)==1 and dr[0]["result"]["winner_key"]=="AWAY" and dr[0]["result"]["away_score"]==3
    print(json.dumps({"SPORTS_PROVIDER_SELF_TEST":"PASS","providers":{"SOCCER":"ESPN_PUBLIC","BASEBALL":"ESPN_PUBLIC","BASKETBALL":"ESPN_PUBLIC","VOLLEYBALL":"KOVO_OFFICIAL_WITH_DAUM_LIVE_FALLBACK"}},ensure_ascii=False))

def live_probe(day:str|None=None):
    day=day or datetime.now(KST).date().isoformat();rows={}
    for sport in SPORTS:
        events,meta=fetch_sport_day(sport,day,include_odds=True);rows[sport]=meta
    print(json.dumps({"SPORTS_PROVIDER_LIVE_PROBE":"PASS","date":day,"providers":rows},ensure_ascii=False))

def kovo_regression_probe():
    day="2023-02-01"
    events,meta=_fetch_daum_volleyball_day(day)
    finals=[e for e in events if e.get("status")=="FINAL" and e.get("result",{}).get("winner_key") in {"HOME","AWAY"}]
    if not finals:
        raise SystemExit("VOLLEY_LIVE_FALLBACK_REGRESSION_FAIL:"+json.dumps(meta,ensure_ascii=False))
    print(json.dumps({"VOLLEY_LIVE_FALLBACK_REGRESSION":"PASS","date":day,"events":len(events),"finals":len(finals),"meta":meta},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");ap.add_argument("--live-probe",action="store_true");ap.add_argument("--kovo-regression-probe",action="store_true");ap.add_argument("--date");a=ap.parse_args()
    if a.self_test:return self_test()
    if a.kovo_regression_probe:return kovo_regression_probe()
    return live_probe(a.date)
if __name__=="__main__":main()
