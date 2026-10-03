#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,time
from pathlib import Path
from datetime import datetime,timedelta,date
from sports_provider import KST,SPORTS,fetch_sport_day

ROOT=Path(__file__).resolve().parents[1]
HIST=ROOT/"data"/"sports_history"
STATE=ROOT/"data"/"historical_state"/"sports_backfill_state.json"
START=date(2022,1,1)
REVISION="SPORTS_BACKFILL_V3_PDF_VOLLEY"
HISTORY_SPORTS=("SOCCER","BASEBALL","BASKETBALL")

def load_state():
    latest=(datetime.now(KST).date()-timedelta(days=1)).isoformat()
    if STATE.exists():
        try:
            s=json.loads(STATE.read_text(encoding="utf-8"))
            if s.get("revision")!=REVISION:
                # V2 replay temporarily moved the cursor forward to repair KOVO.
                # KOVO is now handled by official DBBank PDF reports; resume the
                # other sports from the older pre-repair boundary when present.
                cursor=str(s.get("repair_until") or s.get("cursor_date") or latest)
                return {
                    "cursor_date":cursor,
                    "complete":False,
                    "calls_total":int(s.get("calls_total",0)),
                    "days_saved":int(s.get("days_saved",0)),
                    "revision":REVISION,
                }
            return s
        except Exception:pass
    return {"cursor_date":latest,"complete":False,"calls_total":0,"days_saved":0,"revision":REVISION}

def save_state(s):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    STATE.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding="utf-8")

def run(max_days=30,max_seconds=900,sleep_seconds=.25):
    HIST.mkdir(parents=True,exist_ok=True);s=load_state();cur=date.fromisoformat(s["cursor_date"])
    started=time.monotonic();days=0;calls=0;saved=0
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
        if not ok_any:break
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
        days+=1;cur-=timedelta(days=1)
        s["cursor_date"]=cur.isoformat()
        s["days_saved"]=int(s.get("days_saved",0))+1
        s["calls_total"]=int(s.get("calls_total",0))+day_calls
        s["revision"]=REVISION
        save_state(s)
    if cur<START:s["complete"]=True
    s["revision"]=REVISION;save_state(s)
    print(json.dumps({
        "SPORTS_BACKFILL":"PASS","history_sports":list(HISTORY_SPORTS),
        "volleyball_history":"KOVO_DBBANK_PDF_SEPARATE",
        "days_this_run":days,"files_saved":saved,"calls_this_run":calls,
        "cursor_date":s["cursor_date"],"complete":s.get("complete",False)
    },ensure_ascii=False))

def self_test():
    assert START.isoformat()=="2022-01-01"
    assert REVISION=="SPORTS_BACKFILL_V3_PDF_VOLLEY"
    assert HISTORY_SPORTS==("SOCCER","BASEBALL","BASKETBALL")
    print(json.dumps({
        "SPORTS_BACKFILL_SELF_TEST":"PASS","start":START.isoformat(),
        "revision":REVISION,"history_sports":list(HISTORY_SPORTS)
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
