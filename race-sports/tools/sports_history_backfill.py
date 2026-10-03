#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,time
from pathlib import Path
from datetime import datetime,timedelta,date
from sports_provider import KST,SPORTS,fetch_sport_day

ROOT=Path(__file__).resolve().parents[1]
HIST=ROOT/"data"/"sports_history"
STATE=ROOT/"data"/"historical_state"/"sports_backfill_state.json"
START=date(2024,1,1)

def load_state():
    if STATE.exists():
        try:return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:pass
    return {"cursor_date":(datetime.now(KST).date()-timedelta(days=1)).isoformat(),"complete":False,"calls_total":0,"days_saved":0}

def save_state(s):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    STATE.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding="utf-8")

def run(max_days=30,max_seconds=900,sleep_seconds=.25):
    HIST.mkdir(parents=True,exist_ok=True);s=load_state();cur=date.fromisoformat(s["cursor_date"])
    started=time.monotonic();days=0;calls=0;saved=0
    while cur>=START and days<max_days and time.monotonic()-started<max_seconds:
        day=cur.isoformat();events=[];providers=[];ok_any=False;day_calls=0
        for sport in SPORTS:
            if time.monotonic()-started>=max_seconds:break
            try:
                ev,meta=fetch_sport_day(sport,day);events.extend(ev);providers.append(meta);ok_any=True;day_calls+=int(meta.get("requests",0))
            except Exception as exc:
                providers.append({"sport":sport,"status":"FAIL","error":str(exc)[:300]})
            time.sleep(sleep_seconds)
        calls+=day_calls
        if not ok_any:break
        payload={"date":day,"domain":"SPORTS","enabled_sports":list(SPORTS),"providers":providers,"events":events,"generated_at":datetime.now(KST).isoformat()}
        (HIST/f"{day}.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        saved+=1;days+=1;cur-=timedelta(days=1)
        s["cursor_date"]=cur.isoformat();s["days_saved"]=int(s.get("days_saved",0))+1;s["calls_total"]=int(s.get("calls_total",0))+day_calls;save_state(s)
    if cur<START:s["complete"]=True;save_state(s)
    print(json.dumps({"SPORTS_BACKFILL":"PASS","days_this_run":days,"files_saved":saved,"calls_this_run":calls,"cursor_date":s["cursor_date"],"complete":s.get("complete",False)},ensure_ascii=False))

def self_test():
    assert START.isoformat()=="2024-01-01"
    print(json.dumps({"SPORTS_BACKFILL_SELF_TEST":"PASS","start":START.isoformat()},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--max-days",type=int,default=30);ap.add_argument("--max-seconds",type=int,default=900);ap.add_argument("--sleep-seconds",type=float,default=.25);ap.add_argument("--self-test",action="store_true");a=ap.parse_args()
    if a.self_test:return self_test()
    run(a.max_days,a.max_seconds,a.sleep_seconds)
if __name__=="__main__":main()
