#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, time, urllib.request
from datetime import datetime, date, timezone, timedelta
from typing import Any

KST=timezone(timedelta(hours=9))
ESPN_BASE="https://site.api.espn.com/apis/site/v2/sports"

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
    "VOLLEYBALL":[
        ("volleyball","fivb.m","FIVB Men"),
        ("volleyball","fivb.w","FIVB Women"),
    ],
}
SPORTS={k:{"slug":k.lower()} for k in LEAGUES}
STATUS_BY_STATE={"pre":"SCHEDULED","in":"LIVE","post":"FINAL"}
STATUS_BY_NAME={
    "STATUS_SCHEDULED":"SCHEDULED",
    "STATUS_IN_PROGRESS":"LIVE",
    "STATUS_HALFTIME":"LIVE",
    "STATUS_FINAL":"FINAL",
    "STATUS_FULL_TIME":"FINAL",
    "STATUS_POSTPONED":"POSTPONED",
    "STATUS_CANCELED":"CANCELLED",
    "STATUS_CANCELLED":"CANCELLED",
}

def _http_json(url:str,timeout:int=18,retries:int=2)->dict:
    last=None
    for i in range(retries+1):
        try:
            req=urllib.request.Request(url,headers={
                "Accept":"application/json",
                "User-Agent":"Mozilla/5.0 (compatible; RACEIQ/1.0; +https://github.com/jay1125jay/flowiq-crew-operations)",
            })
            with urllib.request.urlopen(req,timeout=timeout) as r:
                if r.status!=200: raise RuntimeError(f"HTTP_{r.status}")
                raw=r.read()
            obj=json.loads(raw.decode("utf-8"))
            if not isinstance(obj,dict): raise RuntimeError("JSON_NOT_OBJECT")
            return obj
        except Exception as e:
            last=e
            if i<retries: time.sleep(1+i)
    raise RuntimeError(f"FETCH_FAILED:{url}:{last!r}")

def _range_param(day:str)->str:
    d=date.fromisoformat(day)
    a=(d-timedelta(days=1)).strftime("%Y%m%d")
    b=(d+timedelta(days=1)).strftime("%Y%m%d")
    return f"{a}-{b}"

def _league_url(sport_slug:str,league_slug:str,day:str)->str:
    return f"{ESPN_BASE}/{sport_slug}/{league_slug}/scoreboard?dates={_range_param(day)}&limit=500"

def _parse_iso(s:str)->datetime:
    if s.endswith("Z"): s=s[:-1]+"+00:00"
    return datetime.fromisoformat(s).astimezone(KST)

def _competitors(ev:dict):
    comps=ev.get("competitions") or []
    if not comps:return None,None,None
    comp=comps[0] or {}
    home=away=None
    for x in comp.get("competitors") or []:
        if x.get("homeAway")=="home": home=x
        elif x.get("homeAway")=="away": away=x
    return comp,home,away

def _team_name(c:dict|None)->str:
    if not c:return ""
    t=c.get("team") or {}
    return str(t.get("displayName") or t.get("shortDisplayName") or t.get("name") or "")

def _num_score(c:dict|None):
    if not c:return None
    v=c.get("score")
    try:
        f=float(v)
        return int(f) if f.is_integer() else f
    except Exception:return None

def _status(ev:dict,comp:dict)->str:
    t=(comp.get("status") or ev.get("status") or {}).get("type") or {}
    name=str(t.get("name") or "").upper()
    state=str(t.get("state") or "").lower()
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
    home=_team_name(home_c); away=_team_name(away_c)
    if not home or not away:return None
    eid=ev.get("id")
    if eid is None:return None
    status=_status(ev,comp)
    hs=_num_score(home_c); aas=_num_score(away_c)
    outcomes=[{"key":"HOME","name":home},{"key":"AWAY","name":away}]
    if sport=="SOCCER": outcomes.insert(1,{"key":"DRAW","name":"무승부"})
    out={
        "id":f"SPORTS-{sport}-{eid}",
        "provider_event_id":str(eid),
        "domain":"SPORTS",
        "sport":sport,
        "provider":"ESPN_PUBLIC",
        "provider_kind":"PUBLIC_SCORE_FEED",
        "competition":league_name,
        "event_date":requested_day,
        "start_time":dt.strftime("%H:%M"),
        "start_timestamp":int(dt.timestamp()),
        "status":status,
        "title":f"{home} vs {away}",
        "home":home,
        "away":away,
        "market_type":"THREE_WAY" if sport=="SOCCER" else "TWO_WAY",
        "outcomes":outcomes,
        "tier":"TOP",
        "tier_filter":"CONFIGURED_TOP_TIER_LEAGUE",
        "data_state":"FRESH",
        "source_url":source_url,
    }
    if status=="FINAL" and hs is not None and aas is not None:
        out["result"]={
            "official":False,
            "status":"CONFIRMED",
            "home_score":hs,
            "away_score":aas,
            "winner_key":_winner_key(sport,home_c,away_c,hs,aas),
            "source":"ESPN_PUBLIC",
            "updated_at":datetime.now(KST).isoformat(),
        }
    elif hs is not None and aas is not None:
        out["score"]={"home":hs,"away":aas}
    return out

def fetch_sport_day(sport:str,day:str)->tuple[list[dict],dict]:
    if sport not in LEAGUES:raise KeyError(sport)
    all_events=[]; sources=[]; failures=[]
    success=0; raw_count=0
    for sport_slug,league_slug,league_name in LEAGUES[sport]:
        url=_league_url(sport_slug,league_slug,day)
        try:
            obj=_http_json(url)
            raw=obj.get("events")
            if not isinstance(raw,list):raise RuntimeError("EVENTS_NOT_LIST")
            success+=1; raw_count+=len(raw); sources.append(url)
            for ev in raw:
                try:
                    x=parse_event(sport,ev,day,league_name,url)
                    if x:all_events.append(x)
                except Exception:
                    continue
        except Exception as exc:
            failures.append({"league":league_name,"error":str(exc)[:250],"url":url})
    if success==0:
        raise RuntimeError("ALL_LEAGUES_FAILED:"+json.dumps(failures,ensure_ascii=False))
    uniq={e["id"]:e for e in all_events}
    events=sorted(uniq.values(),key=lambda e:(e.get("start_timestamp",0),e["id"]))
    return events,{
        "sport":sport,
        "status":"PASS" if not failures else "PARTIAL",
        "requests":len(LEAGUES[sport]),
        "successful_requests":success,
        "raw_events":raw_count,
        "top_tier_events":len(events),
        "source_urls":sources,
        "failures":failures,
    }

def _fixture(sport:str)->dict:
    iso="2026-10-04T03:00:00Z"
    return {
        "id":"401234567","date":iso,
        "competitions":[{
            "status":{"type":{"name":"STATUS_FINAL","state":"post","completed":True}},
            "competitors":[
                {"homeAway":"home","winner":True,"score":"2","team":{"displayName":"Home FC"}},
                {"homeAway":"away","winner":False,"score":"1","team":{"displayName":"Away FC"}},
            ],
        }],
    }

def self_test():
    for sport in LEAGUES:
        x=parse_event(sport,_fixture(sport),"2026-10-04","TEST TOP","https://example.test")
        assert x and x["tier"]=="TOP" and x["status"]=="FINAL"
        assert x["result"]["winner_key"]=="HOME"
        keys=[o["key"] for o in x["outcomes"]]
        assert keys==(["HOME","DRAW","AWAY"] if sport=="SOCCER" else ["HOME","AWAY"])
    print(json.dumps({"SPORTS_PROVIDER_SELF_TEST":"PASS","provider":"ESPN_PUBLIC","sports":list(LEAGUES)},ensure_ascii=False))

def live_probe(day:str|None=None):
    day=day or datetime.now(KST).date().isoformat()
    rows={}
    for sport in LEAGUES:
        events,meta=fetch_sport_day(sport,day)
        rows[sport]=meta
    print(json.dumps({"SPORTS_PROVIDER_LIVE_PROBE":"PASS","date":day,"providers":rows},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--live-probe",action="store_true")
    ap.add_argument("--date")
    a=ap.parse_args()
    if a.self_test:return self_test()
    return live_probe(a.date)
if __name__=="__main__":main()
