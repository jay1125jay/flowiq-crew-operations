#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, time
from pathlib import Path
from datetime import datetime, timedelta, date
from sports_provider import KST, SPORTS, fetch_sport_day

ROOT=Path(__file__).resolve().parents[1]
HIST=ROOT/"data"/"sports_history"
STATE=ROOT/"data"/"historical_state"/"sports_backfill_state.json"
START=date(2024,1,1)

def load_state():
    if STATE.exists():
        try:return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:pass
    cur=datetime.now(KST).date()-timedelta(days=1)
    return {"cursor_date":cur.isoformat(),"complete":False,"calls_total":0,"days_saved":0}

def save_state(s):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    STATE.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding="utf-8")

def run(max_days=30,max_seconds=900,sleep_seconds=.35):
    HIST.mkdir(parents=True,exist_ok=True)
    s=load_state(); started=time.monotonic(); days=0; calls=0; saved=0
    cur=date.fromisoformat(s["cursor_date"])
    while cur>=START and days<max_days and time.monotonic()-started<max_seconds:
        day=cur.isoformat(); all_events=[]; providers=[]; ok_any=False
        for sport in SPORTS:
            if time.monotonic()-started>=max_seconds: break
            try:
                ev,meta=fetch_sport_day(sport,day)
                all_events.extend(ev); providers.append(meta); ok_any=True
            except Exception as exc:
                providers.append({"sport":sport,"status":"FAIL","error":str(exc)[:300]})
            calls+=1
            time.sleep(sleep_seconds)
        if ok_any:
            payload={
                "date":day,"domain":"SPORTS","enabled_sports":list(SPORTS),
                "providers":providers,"events":all_events,
                "generated_at":datetime.now(KST).isoformat(),
            }
            (HIST/f"{day}.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
            saved+=1
            cur-=timedelta(days=1)
            s["cursor_date"]=cur.isoformat()
            s["days_saved"]=int(s.get("days_saved",0))+1
            s["calls_total"]=int(s.get("calls_total",0))+len(SPORTS)
            save_state(s)
            days+=1
        else:
            # do not advance on total provider failure
            break
    if cur<START:
        s["complete"]=True; save_state(s)
    print(json.dumps({"SPORTS_BACKFILL":"PASS","days_this_run":days,"files_saved":saved,"calls_this_run":calls,"cursor_date":s["cursor_date"],"complete":s.get("complete",False)},ensure_ascii=False))

def self_test():
    s={"cursor_date":"2026-10-03","complete":False}
    assert date.fromisoformat(s["cursor_date"])>START
    print(json.dumps({"SPORTS_BACKFILL_SELF_TEST":"PASS","start":START.isoformat()},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--max-days",type=int,default=30)
    ap.add_argument("--max-seconds",type=int,default=900)
    ap.add_argument("--sleep-seconds",type=float,default=.35)
    ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    if a.self_test:return self_test()
    run(a.max_days,a.max_seconds,a.sleep_seconds)
if __name__=="__main__":main()
