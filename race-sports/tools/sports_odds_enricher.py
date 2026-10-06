#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SNAPSHOT=ROOT/"data"/"sports_today.json"
STATE=ROOT/"data"/"model_state"/"sports_odds_provider_state.json"
KST=timezone(timedelta(hours=9))
BASE="https://api.sportsgameodds.com/v2/events"

SPORT_IDS={
    "SOCCER":"SOCCER",
    "BASEBALL":"BASEBALL",
    "BASKETBALL":"BASKETBALL",
    "VOLLEYBALL":"VOLLEYBALL",
}
ODD_IDS={
    "SOCCER":{
        "HOME":"points-home-reg-ml3way-home",
        "DRAW":"points-all-reg-ml3way-draw",
        "AWAY":"points-away-reg-ml3way-away",
    },
    "BASEBALL":{
        "HOME":"points-home-game-ml-home",
        "AWAY":"points-away-game-ml-away",
    },
    "BASKETBALL":{
        "HOME":"points-home-game-ml-home",
        "AWAY":"points-away-game-ml-away",
    },
    "VOLLEYBALL":{
        "HOME":"points-home-game-ml-home",
        "AWAY":"points-away-game-ml-away",
    },
}
PREFERRED_BOOKS=[
    "bet365","pinnacle","draftkings","fanduel","betmgm","caesars",
    "espnbet","bovada","unibet","williamhill"
]

def norm(s:str)->str:
    s=unicodedata.normalize("NFKD",str(s or "")).lower()
    s="".join(ch for ch in s if ch.isalnum())
    for token in ("fc","cf","club","basketball","baseball","volleyball","the"):
        if s.endswith(token) and len(s)>len(token)+3:
            s=s[:-len(token)]
    return s

def team_name(x):
    if not isinstance(x,dict):return ""
    names=x.get("names") or {}
    return str(names.get("long") or names.get("medium") or names.get("short") or x.get("name") or "")

def american_to_decimal(v):
    try:
        if isinstance(v,str):
            t=v.strip().upper()
            if t in {"EVEN","EV","PK","PICK"}:return 2.0
            v=float(t.replace("+",""))
        else:v=float(v)
        if not math.isfinite(v) or v==0:return None
        return round(1+v/100,4) if v>0 else round(1+100/abs(v),4)
    except Exception:return None

def _book_key(s):
    return re.sub(r"[^a-z0-9]","",str(s or "").lower())

def _book_rank(k):
    k=_book_key(k)
    try:return PREFERRED_BOOKS.index(k)
    except ValueError:return 999

def _request(params:dict,key:str)->dict:
    qs=urllib.parse.urlencode(params)
    req=urllib.request.Request(
        BASE+"?"+qs,
        headers={
            "x-api-key":key,
            "Accept":"application/json",
            "User-Agent":"RACEIQ/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req,timeout=25) as r:
            if r.status!=200:raise RuntimeError(f"HTTP_{r.status}")
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body=exc.read().decode("utf-8","replace")[:1200]
        except Exception:
            body=""
        raise RuntimeError(f"HTTP_{exc.code}: {body or exc.reason}") from exc

def _market_books(event:dict,sport:str)->dict:
    odds=event.get("odds") or {}
    out={}
    for side,odd_id in ODD_IDS[sport].items():
        m=odds.get(odd_id)
        if not isinstance(m,dict):continue
        books=m.get("byBookmaker") or {}
        rows=[]
        for bookmaker,v in books.items():
            if not isinstance(v,dict) or v.get("available") is False:continue
            dec=american_to_decimal(v.get("odds"))
            if not dec or dec<=1:continue
            rows.append({
                "bookmaker":str(bookmaker),
                "odds":dec,
                "american_odds":str(v.get("odds")),
                "updated_at":v.get("lastUpdatedAt"),
                "deeplink":v.get("deeplink"),
            })
        rows.sort(key=lambda x:(_book_rank(x["bookmaker"]),-x["odds"]))
        if rows:out[side]=rows
    return out

def _choose(rows:list[dict]):
    return rows[0] if rows else None

def _match(local:dict,remote:dict)->bool:
    lt=(norm(local.get("home")),norm(local.get("away")))
    teams=remote.get("teams") or {}
    rt=(norm(team_name(teams.get("home"))),norm(team_name(teams.get("away"))))
    if not all(lt+rt):return False
    exact=lt==rt
    fuzzy=(lt[0] in rt[0] or rt[0] in lt[0]) and (lt[1] in rt[1] or rt[1] in lt[1])
    if not (exact or fuzzy):return False
    try:
        lts=int(local.get("start_timestamp") or 0)
        rdt=datetime.fromisoformat(str((remote.get("status") or {}).get("startsAt")).replace("Z","+00:00"))
        rts=int(rdt.timestamp())
        return abs(lts-rts)<=6*3600
    except Exception:
        return True

def fetch_for_sport(sport:str,day:str,key:str)->tuple[list[dict],dict]:
    d=datetime.fromisoformat(day).replace(tzinfo=KST)
    after=(d-timedelta(hours=9)).astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    before=(d+timedelta(days=1,hours=15)).astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    params={
        "sportID":SPORT_IDS[sport],
        "oddsPresent":"true",
        "startsAfter":after,
        "startsBefore":before,
        "includeOpenCloseOdds":"true",
        "limit":"100",
    }
    bookmaker_filter=os.getenv("SPORTSGAMEODDS_BOOKMAKERS","").strip()
    if bookmaker_filter:params["bookmakerID"]=bookmaker_filter
    obj=_request(params,key)
    rows=obj.get("data")
    if not isinstance(rows,list):raise RuntimeError("SPORTSGAMEODDS_DATA_NOT_LIST")
    return rows,{
        "sport":sport,
        "events":len(rows),
        "next_cursor":obj.get("nextCursor"),
        "bookmaker_filter":bookmaker_filter or "PLAN_ACCESSIBLE_BOOKMAKERS",
    }

def enrich(path:Path=SNAPSHOT)->dict:
    key=os.getenv("SPORTSGAMEODDS_API_KEY","").strip()
    payload=json.loads(path.read_text(encoding="utf-8"))
    now=datetime.now(KST).isoformat()
    if not key:
        result={"status":"KEY_MISSING","events_enriched":0,"outcomes_enriched":0,"updated_at":now}
        payload["odds_provider"]={"provider":"SportsGameOdds",**result}
        payload["providers"]=[p for p in payload.get("providers",[]) if p.get("provider")!="SPORTS_ODDS_MULTIBOOK"]+[{"provider":"SPORTS_ODDS_MULTIBOOK","sport":"ALL",**result}]
        tmp=path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        tmp.replace(path)
        STATE.parent.mkdir(parents=True,exist_ok=True)
        STATE.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"SPORTS_ODDS_ENRICH":"SKIP",**result},ensure_ascii=False))
        return result

    day=str(payload.get("date"))
    remote={};meta=[];errors=[]
    for sport in SPORT_IDS:
        try:
            rows,m=fetch_for_sport(sport,day,key)
            remote[sport]=rows;meta.append(m)
        except Exception as exc:
            remote[sport]=[]
            errors.append({"sport":sport,"error":str(exc)[:1200]})

    events_enriched=0;outcomes_enriched=0
    for e in payload.get("events",[]):
        sport=e.get("sport")
        if sport not in remote:continue
        rem=next((x for x in remote[sport] if _match(e,x)),None)
        if not rem:continue
        books=_market_books(rem,sport)
        if len(books)<2:continue
        applied=0
        for o in e.get("outcomes",[]):
            side=o.get("key")
            rows=books.get(side) or []
            chosen=_choose(rows)
            if not chosen:continue
            o["odds"]=chosen["odds"]
            o["odds_source"]="SPORTSGAMEODDS"
            o["odds_provider"]=chosen["bookmaker"]
            o["odds_capture_mode"]="PRE_GAME_MULTI_BOOK"
            o["odds_updated_at"]=chosen.get("updated_at") or now
            o["bookmaker_odds"]=rows
            o["odds_data_state"]="FRESH"
            applied+=1
        needed=3 if sport=="SOCCER" else 2
        if applied==needed:
            e["odds_source"]="SPORTSGAMEODDS"
            e["odds_state"]="MULTI_BOOK_SOURCE_LABELED"
            e["odds_event_id"]=rem.get("eventID")
            e["odds_books"]=sorted({x["bookmaker"] for rows in books.values() for x in rows})
            e["odds_data_state"]="FRESH"
            events_enriched+=1
            outcomes_enriched+=applied

    payload["odds_provider"]={
        "provider":"SportsGameOdds",
        "status":"PASS" if not errors else "PARTIAL",
        "events_enriched":events_enriched,
        "outcomes_enriched":outcomes_enriched,
        "meta":meta,
        "errors":errors,
        "updated_at":now,
    }
    payload["providers"]=[p for p in payload.get("providers",[]) if p.get("provider")!="SPORTS_ODDS_MULTIBOOK"]+[{
        "provider":"SPORTS_ODDS_MULTIBOOK","sport":"ALL",
        "status":"PASS" if not errors else "PARTIAL",
        "events_enriched":events_enriched,"outcomes_enriched":outcomes_enriched,
        "errors":errors,"updated_at":now,
    }]
    tmp=path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(path)

    result={
        "status":"PASS" if not errors else "PARTIAL",
        "events_enriched":events_enriched,
        "outcomes_enriched":outcomes_enriched,
        "errors":errors,
        "updated_at":now,
    }
    STATE.parent.mkdir(parents=True,exist_ok=True)
    STATE.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"SPORTS_ODDS_ENRICH":"PASS",**result},ensure_ascii=False))
    return result

def self_test():
    fixture={
        "teams":{
            "home":{"names":{"long":"Los Angeles Dodgers"}},
            "away":{"names":{"long":"Atlanta Braves"}},
        },
        "status":{"startsAt":"2026-10-03T20:00:00Z"},
        "odds":{
            "points-home-game-ml-home":{"byBookmaker":{"draftkings":{"odds":"-150","available":True,"lastUpdatedAt":"2026-10-03T12:00:00Z"},"pinnacle":{"odds":"-145","available":True,"lastUpdatedAt":"2026-10-03T12:00:01Z"}}},
            "points-away-game-ml-away":{"byBookmaker":{"draftkings":{"odds":"+130","available":True,"lastUpdatedAt":"2026-10-03T12:00:00Z"},"pinnacle":{"odds":"+135","available":True,"lastUpdatedAt":"2026-10-03T12:00:01Z"}}},
        }
    }
    b=_market_books(fixture,"BASEBALL")
    assert b["HOME"][0]["bookmaker"]=="pinnacle"
    assert abs(b["HOME"][0]["odds"]-1.6897)<1e-4
    assert abs(b["AWAY"][0]["odds"]-2.35)<1e-9
    local={"home":"Los Angeles Dodgers","away":"Atlanta Braves","start_timestamp":int(datetime(2026,10,3,20,tzinfo=timezone.utc).timestamp())}
    assert _match(local,fixture)
    soccer={"odds":{"points-home-reg-ml3way-home":{"byBookmaker":{"bet365":{"odds":"+120","available":True}}},"points-all-reg-ml3way-draw":{"byBookmaker":{"bet365":{"odds":"+250","available":True}}},"points-away-reg-ml3way-away":{"byBookmaker":{"bet365":{"odds":"+220","available":True}}}}}
    sb=_market_books(soccer,"SOCCER")
    assert set(sb)=={"HOME","DRAW","AWAY"}
    print(json.dumps({"SPORTS_ODDS_PROVIDER_SELF_TEST":"PASS"},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--path",default=str(SNAPSHOT))
    a=ap.parse_args()
    if a.self_test:return self_test()
    enrich(Path(a.path))

if __name__=="__main__":
    main()
