#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,time
from pathlib import Path
from datetime import datetime,timedelta,date
from sports_provider import KST,SPORTS,fetch_sport_day

ROOT=Path(__file__).resolve().parents[1]
HIST=ROOT/"data"/"sports_history"
STATE=ROOT/"data"/"historical_state"/"sports_backfill_state.json"
START=date(2018,1,1)
REVISION="SPORTS_BACKFILL_V4_DEEP_2018"
HISTORY_SPORTS=("SOCCER","BASEBALL","BASKETBALL")


def _safe_date(raw:str|None,fallback:date)->date:
    try:return date.fromisoformat(str(raw))
    except Exception:return fallback


def load_state():
    latest=(datetime.now(KST).date()-timedelta(days=1))
    if STATE.exists():
        try:
            s=json.loads(STATE.read_text(encoding="utf-8"))
            cursor=_safe_date(s.get("cursor_date"),latest)
            if s.get("revision")!=REVISION:
                # Keep the deepest known cursor when expanding the historical
                # target. A previously complete V3 checkpoint only meant that
                # the old 2022 boundary was finished; V4 continues from there.
                if s.get("repair_until"):
                    repair=_safe_date(s.get("repair_until"),cursor)
                    cursor=min(cursor,repair)
                return {
                    "cursor_date":cursor.isoformat(),
                    "complete":cursor<START,
                    "calls_total":int(s.get("calls_total",0)),
                    "days_saved":int(s.get("days_saved",0)),
                    "revision":REVISION,
                    "target_start_date":START.isoformat(),
                }
            s["target_start_date"]=START.isoformat()
            s["complete"]=bool(s.get("complete",False) and cursor<START)
            return s
        except Exception:
            pass
    return {
        "cursor_date":latest.isoformat(),
        "complete":False,
        "calls_total":0,
        "days_saved":0,
        "revision":REVISION,
        "target_start_date":START.isoformat(),
    }


def save_state(s):
    s["revision"]=REVISION
    s["target_start_date"]=START.isoformat()
    STATE.parent.mkdir(parents=True,exist_ok=True)
    STATE.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding="utf-8")


def run(max_days=30,max_seconds=900,sleep_seconds=.25):
    HIST.mkdir(parents=True,exist_ok=True)
    s=load_state()
    cur=date.fromisoformat(s["cursor_date"])
    started=time.monotonic();days=0;calls=0;saved=0

    if cur<START:
        s["complete"]=True
        save_state(s)
        print(json.dumps({
            "SPORTS_BACKFILL":"PASS","history_sports":list(HISTORY_SPORTS),
            "volleyball_history":"KOVO_DBBANK_PDF_SEPARATE",
            "days_this_run":0,"files_saved":0,"calls_this_run":0,
            "cursor_date":s["cursor_date"],"target_start_date":START.isoformat(),
            "complete":True
        },ensure_ascii=False))
        return

    s["complete"]=False
    save_state(s)

    while cur>=START and days<max_days and time.monotonic()-started<max_seconds:
        day=cur.isoformat();events=[];providers=[];ok_any=False;day_calls=0
        existing=HIST/f"{day}.json"

        # Preserve official KOVO PDF events while refreshing the other sports.
        if existing.exists():
            try:
                prev=json.loads(existing.read_text(encoding="utf-8"))
                events=[e for e in prev.get("events",[]) if e.get("sport")=="VOLLEYBALL"]
                providers=[m for m in prev.get("providers",[]) if m.get("sport")=="VOLLEYBALL"]
            except Exception:
                events=[];providers=[]

        for sport in HISTORY_SPORTS:
            if time.monotonic()-started>=max_seconds:break
            try:
                ev,meta=fetch_sport_day(sport,day)
                events.extend(ev);providers.append(meta);ok_any=True
                day_calls+=int(meta.get("requests",0))
            except Exception as exc:
                providers.append({"sport":sport,"status":"FAIL","error":str(exc)[:300]})
            time.sleep(sleep_seconds)

        calls+=day_calls
        if not ok_any:
            break

        events.sort(key=lambda e:(e.get("start_timestamp",0),e.get("sport",""),e.get("id","")))
        payload={
            "date":day,"domain":"SPORTS","enabled_sports":list(SPORTS),
            "providers":providers,"events":events,
            "generated_at":datetime.now(KST).isoformat()
        }
        new=json.dumps(payload,ensure_ascii=False,indent=2)
        old=existing.read_text(encoding="utf-8") if existing.exists() else None
        if new!=old:
            existing.write_text(new,encoding="utf-8");saved+=1

        days+=1
        cur-=timedelta(days=1)
        s["cursor_date"]=cur.isoformat()
        s["days_saved"]=int(s.get("days_saved",0))+1
        s["calls_total"]=int(s.get("calls_total",0))+day_calls
        s["complete"]=cur<START
        save_state(s)

    s["complete"]=cur<START
    save_state(s)
    print(json.dumps({
        "SPORTS_BACKFILL":"PASS","history_sports":list(HISTORY_SPORTS),
        "volleyball_history":"KOVO_DBBANK_PDF_SEPARATE",
        "days_this_run":days,"files_saved":saved,"calls_this_run":calls,
        "cursor_date":s["cursor_date"],"target_start_date":START.isoformat(),
        "complete":s.get("complete",False)
    },ensure_ascii=False))


def self_test():
    assert START.isoformat()=="2018-01-01"
    assert REVISION=="SPORTS_BACKFILL_V4_DEEP_2018"
    assert HISTORY_SPORTS==("SOCCER","BASEBALL","BASKETBALL")
    old={
        "cursor_date":"2021-12-31","complete":True,"calls_total":45245,
        "days_saved":1957,"revision":"SPORTS_BACKFILL_V3_PDF_VOLLEY"
    }
    cursor=_safe_date(old["cursor_date"],date.today())
    assert cursor>=START and old["complete"] is True
    print(json.dumps({
        "SPORTS_BACKFILL_SELF_TEST":"PASS","start":START.isoformat(),
        "revision":REVISION,"history_sports":list(HISTORY_SPORTS),
        "migration_from_v3_cursor":cursor.isoformat()
    },ensure_ascii=False))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--max-days",type=int,default=30)
    ap.add_argument("--max-seconds",type=int,default=900)
    ap.add_argument("--sleep-seconds",type=float,default=.25)
    ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    if a.self_test:return self_test()
    run(a.max_days,a.max_seconds,a.sleep_seconds)


if __name__=="__main__":
    main()
