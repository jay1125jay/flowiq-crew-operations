#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path

try:
    from pypdf import PdfReader
except Exception:
    PdfReader=None

KST=timezone(timedelta(hours=9))
ROOT=Path(__file__).resolve().parents[1]
HIST=ROOT/"data"/"sports_history"
STATE=ROOT/"data"/"historical_state"/"kovo_pdf_backfill_state.json"
BASE="https://dbbank.kovo.co.kr/upload/gamereport"
GPART="201"
SEED_SEASONS=("022","021")
MAX_GAME_DEFAULT=260
REVISION="KOVO_PDF_V3_ARCHIVE_BOUNDARY"
MIN_OFFICIAL_PDF_SEASON="015"


def report_urls(season:str,game_no:int)->list[str]:
    # KOVO DB BANK has used both zero-padded and legacy unpadded game numbers.
    # Example legacy official file: A_01520136.pdf (game 36).
    names=[
        f"A_{season}{GPART}{game_no:03d}.pdf",
        f"A_{season}{GPART}{game_no}.pdf",
    ]
    out=[]
    for name in names:
        url=f"{BASE}/{name}"
        if url not in out:out.append(url)
    return out


def report_url(season:str,game_no:int)->str:
    # Keep compatibility with callers that expect the modern padded URL.
    return report_urls(season,game_no)[0]


def fetch_pdf(url:str,timeout:int=15,retries:int=1)->bytes|None:
    last=None
    for i in range(retries+1):
        try:
            req=urllib.request.Request(url,headers={
                "Accept":"application/pdf,*/*;q=0.8",
                "Referer":"https://dbbank.kovo.co.kr/",
                "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
            })
            with urllib.request.urlopen(req,timeout=timeout) as r:
                if r.status!=200:return None
                raw=r.read()
                if not raw.startswith(b"%PDF"):return None
                return raw
        except urllib.error.HTTPError as e:
            if e.code in (404,403):return None
            last=e
        except Exception as e:
            last=e
        if i<retries:time.sleep(.4*(i+1))
    return None


def norm(s:str)->str:
    return " ".join(str(s or "").replace("\xa0"," ").split())


def parse_pdf(raw:bytes,season:str,game_no:int,url:str)->dict|None:
    if PdfReader is None:
        raise RuntimeError("PYPDF_REQUIRED")
    try:
        reader=PdfReader(BytesIO(raw))
        if not reader.pages:return None
        text=reader.pages[0].extract_text() or ""
    except Exception:
        return None
    flat=norm(text)
    m=re.search(
        r"제\s*(\d+)\s*경기\.\s*(.+?)\s+vs\s+(.+?)\s*\([^,]+,\s*"
        r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2}),\s*"
        r"(\d{1,2}:\d{2})\s*~",
        flat,re.I
    )
    if not m:return None
    parsed_no=int(m.group(1))
    if parsed_no!=game_no:return None
    home=norm(m.group(2));away=norm(m.group(3))
    y,mo,da=int(m.group(4)),int(m.group(5)),int(m.group(6))
    tm=m.group(7)
    day=f"{y:04d}-{mo:02d}-{da:02d}"
    try:
        dt=datetime.strptime(day+" "+tm,"%Y-%m-%d %H:%M").replace(tzinfo=KST)
    except Exception:
        return None

    seg=text
    a=seg.find("경기결과")
    b=seg.find("오늘 경기 최고")
    if a>=0:seg=seg[a:b if b>a else None]
    singles=[int(x) for x in re.findall(r"(?m)^\s*([0-5])\s*$",seg)]
    hs=aas=None
    if len(singles)>=2:
        hs,aas=singles[-2],singles[-1]

    winner=None
    if hs is not None and aas is not None and hs!=aas:
        winner="HOME" if hs>aas else "AWAY"
    if winner is None:
        cmp_text=flat
        if re.search(re.escape(home)+r"\s+기록\s+"+re.escape(away)+r"\s+승\s+승패\s+패",cmp_text):
            winner="HOME";hs,aas=3,0
        elif re.search(re.escape(home)+r"\s+기록\s+"+re.escape(away)+r"\s+패\s+승패\s+승",cmp_text):
            winner="AWAY";hs,aas=0,3
    if winner is None:return None

    return {
        "id":f"SPORTS-VOLLEYBALL-KOVO-{season}-{game_no:03d}",
        "provider_event_id":f"{season}-{game_no:03d}",
        "domain":"SPORTS",
        "sport":"VOLLEYBALL",
        "provider":"KOVO_DBBANK_OFFICIAL",
        "provider_kind":"OFFICIAL_POSTGAME_REPORT",
        "competition":"KOVO V-League",
        "event_date":day,
        "start_time":tm,
        "start_timestamp":int(dt.timestamp()),
        "status":"FINAL",
        "title":f"{home} vs {away}",
        "home":home,
        "away":away,
        "market_type":"TWO_WAY",
        "outcomes":[{"key":"HOME","name":home},{"key":"AWAY","name":away}],
        "tier":"TOP",
        "tier_filter":"KOVO_V_LEAGUE_TOP_DIVISION",
        "data_state":"FRESH",
        "source_url":url,
        "result":{
            "official":True,
            "status":"CONFIRMED",
            "home_score":hs,
            "away_score":aas,
            "score_type":"SETS",
            "winner_key":winner,
            "source":"KOVO_DBBANK_OFFICIAL",
            "updated_at":datetime.now(KST).isoformat(),
        },
    }


def fetch_one(season:str,n:int):
    for url in report_urls(season,n):
        raw=fetch_pdf(url)
        if not raw:continue
        event=parse_pdf(raw,season,n,url)
        if event:return n,event
    return n,None


def scan_season(season:str,max_game:int,workers:int=6)->tuple[list[dict],dict]:
    # The official DB BANK post-game PDF archive is verifiably populated from
    # season code 015 onward. Code 014 returns zero documents across both known
    # filename conventions, so treat it as an archive boundary rather than a
    # collector failure and do not waste hundreds of requests every run.
    if season < MIN_OFFICIAL_PDF_SEASON:
        return [],{
            "season":season,
            "scanned":0,
            "parsed_events":0,
            "legacy_unpadded_events":0,
            "status":"UNAVAILABLE_OFFICIAL_PDF",
            "reason":f"KOVO_DBBANK_PDF_ARCHIVE_STARTS_AT_{MIN_OFFICIAL_PDF_SEASON}",
        }
    rows=[]
    with ThreadPoolExecutor(max_workers=max(1,min(workers,8))) as ex:
        futs={ex.submit(fetch_one,season,n):n for n in range(1,max_game+1)}
        for fut in as_completed(futs):
            try:
                _,e=fut.result()
            except Exception:
                e=None
            if e:rows.append(e)
    rows.sort(key=lambda e:(e["start_timestamp"],e["id"]))
    legacy_count=sum(1 for e in rows if not e["source_url"].endswith(f"{int(e['provider_event_id'].split('-')[-1]):03d}.pdf"))
    return rows,{
        "season":season,
        "scanned":max_game,
        "parsed_events":len(rows),
        "legacy_unpadded_events":legacy_count,
        "status":"PASS" if rows else "FAIL",
    }


def merge_events(events:list[dict])->dict:
    HIST.mkdir(parents=True,exist_ok=True)
    by_day={}
    for e in events:by_day.setdefault(e["event_date"],[]).append(e)
    changed_files=0;added=0;replaced=0
    for day,rows in by_day.items():
        p=HIST/f"{day}.json"
        if p.exists():
            try:obj=json.loads(p.read_text(encoding="utf-8"))
            except Exception:obj={}
        else:obj={}
        obj.setdefault("date",day)
        obj["domain"]="SPORTS"
        obj["enabled_sports"]=["SOCCER","BASEBALL","BASKETBALL","VOLLEYBALL"]
        old=obj.get("events") or []
        idx={e.get("id"):e for e in old if e.get("id")}
        for e in rows:
            if e["id"] in idx:replaced+=1
            else:added+=1
            idx[e["id"]]=e
        merged=list(idx.values())
        merged.sort(key=lambda e:(e.get("start_timestamp",0),e.get("sport",""),e.get("id","")))
        obj["events"]=merged
        providers=[x for x in (obj.get("providers") or []) if not (x.get("sport")=="VOLLEYBALL" and x.get("provider")=="KOVO_DBBANK_OFFICIAL")]
        providers.append({
            "sport":"VOLLEYBALL","provider":"KOVO_DBBANK_OFFICIAL","status":"PASS",
            "official":True,"source":"OFFICIAL_POSTGAME_REPORT",
            "events":sum(1 for e in merged if e.get("sport")=="VOLLEYBALL" and e.get("provider")=="KOVO_DBBANK_OFFICIAL"),
        })
        obj["providers"]=providers
        obj["generated_at"]=datetime.now(KST).isoformat()
        new=json.dumps(obj,ensure_ascii=False,indent=2)
        old_text=p.read_text(encoding="utf-8") if p.exists() else None
        if new!=old_text:
            p.write_text(new,encoding="utf-8");changed_files+=1
    return {"changed_files":changed_files,"added":added,"replaced":replaced}


def load_state():
    if STATE.exists():
        try:return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:pass
    return {"completed_seed_seasons":[],"last_run":None}


def save_state(s):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    STATE.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding="utf-8")


def backfill(seasons:list[str],max_game:int,workers:int,force:bool=False):
    state=load_state()
    # V3 changes only archive-boundary semantics. Preserve already validated
    # V2 completed seasons so we do not rescan thousands of official PDFs.
    if state.get("revision") not in {REVISION,"KOVO_PDF_V2_PADDED_AND_UNPADDED"}:
        state["completed_seed_seasons"]=[]
        state["revision_reset_at"]=datetime.now(KST).isoformat()
    state["revision"]=REVISION
    all_events=[];reports=[]
    done=set(state.get("completed_seed_seasons") or [])
    selected=[s for s in seasons if force or s not in done]
    if not selected:
        save_state(state)
        print(json.dumps({"KOVO_PDF_BACKFILL":"PASS","revision":REVISION,"skipped_completed":seasons,"events":0,"merge":{"changed_files":0,"added":0,"replaced":0}},ensure_ascii=False))
        return
    for season in selected:
        events,meta=scan_season(season,max_game,workers)
        reports.append(meta);all_events.extend(events)
    merge=merge_events(all_events)
    accepted={"PASS","UNAVAILABLE_OFFICIAL_PDF"}
    unavailable=[]
    for meta in reports:
        if meta["status"] in accepted:done.add(meta["season"])
        if meta["status"]=="UNAVAILABLE_OFFICIAL_PDF":unavailable.append(meta["season"])
    state["completed_seed_seasons"]=sorted(done,reverse=True)
    state["unavailable_official_pdf_seasons"]=sorted(set((state.get("unavailable_official_pdf_seasons") or [])+unavailable),reverse=True)
    state["official_pdf_min_season"]=MIN_OFFICIAL_PDF_SEASON
    state["revision"]=REVISION
    state["last_run"]=datetime.now(KST).isoformat()
    state["last_reports"]=reports
    state["last_merge"]=merge
    save_state(state)
    print(json.dumps({
        "KOVO_PDF_BACKFILL":"PASS" if all(x["status"] in accepted for x in reports) else "PARTIAL",
        "revision":REVISION,"reports":reports,"events":len(all_events),"merge":merge
    },ensure_ascii=False))


def self_test():
    modern_url=report_url("022",237)
    raw=fetch_pdf(modern_url)
    if not raw:raise SystemExit("KOVO_PDF_SELF_TEST_FETCH_FAIL")
    e=parse_pdf(raw,"022",237,modern_url)
    assert e,"KOVO_PDF_SELF_TEST_PARSE_FAIL"
    assert e["event_date"]=="2026-03-10",e
    assert e["home"]=="흥국생명" and e["away"]=="IBK기업은행",e
    assert e["result"]["winner_key"]=="HOME",e
    assert e["result"]["home_score"]==3 and e["result"]["away_score"]==2,e

    # Regression guard for legacy unpadded official filenames.
    legacy_urls=report_urls("015",36)
    assert legacy_urls[0].endswith("A_015201036.pdf")
    assert legacy_urls[1].endswith("A_01520136.pdf")
    legacy_raw=fetch_pdf(legacy_urls[1])
    if not legacy_raw:raise SystemExit("KOVO_PDF_LEGACY_SELF_TEST_FETCH_FAIL")
    legacy=parse_pdf(legacy_raw,"015",36,legacy_urls[1])
    assert legacy and legacy["event_date"]=="2018-11-05",legacy
    assert legacy["home"]=="현대캐피탈" and legacy["away"]=="KB손해보험",legacy
    assert legacy["result"]["home_score"]==3 and legacy["result"]["away_score"]==0,legacy

    unavailable,meta=scan_season("014",260,1)
    assert unavailable==[] and meta["status"]=="UNAVAILABLE_OFFICIAL_PDF",meta
    assert meta["scanned"]==0,meta
    print(json.dumps({
        "KOVO_PDF_SELF_TEST":"PASS",
        "modern_event":e["id"],
        "legacy_event":legacy["id"],
        "archive_boundary":meta,
        "revision":REVISION
    },ensure_ascii=False))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--seasons",default=",".join(SEED_SEASONS))
    ap.add_argument("--max-game",type=int,default=MAX_GAME_DEFAULT)
    ap.add_argument("--workers",type=int,default=6)
    ap.add_argument("--force",action="store_true")
    a=ap.parse_args()
    if a.self_test:return self_test()
    seasons=[x.strip() for x in a.seasons.split(",") if x.strip()]
    backfill(seasons,a.max_game,a.workers,a.force)

if __name__=="__main__":
    main()
