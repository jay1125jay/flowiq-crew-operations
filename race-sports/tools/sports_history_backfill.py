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
REVISION="SPORTS_BACKFILL_V2_KOVO_REPAIR"

def load_state():
    latest=(datetime.now(KST).date()-timedelta(days=1)).isoformat()
    if STATE.exists():
        try:
            s=json.loads(STATE.read_text(encoding="utf-8"))
            if s.get("revision")!=REVISION:
                # Provider/parser contract changed: replay recent history so old
                # zero-event volleyball snapshots are repaired deterministically.
                return {
                    "cursor_date":latest,"complete":False,
                    "calls_total":int(s.get("calls_total",0)),
                    "days_saved":int(s.get("days_saved",0)),
                    "revision":REVISION,"repair_replay":True,
                    "repair_until":str(s.get("cursor_date") or latest)
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
        repair=bool(s.get("repair_replay"))
        existing=HIST/f"{day}.json"
        if repair and existing.exists():
            try:
                prev=json.loads(existing.read_text(encoding="utf-8"))
                events=[e for e in prev.get("events",[]) if e.get("sport")!="VOLLEYBALL"]
                providers=[m for m in prev.get("providers",[]) if m.get("sport")!="VOLLEYBALL"]
            except Exception:
                events=[];providers=[]
            try:
                ev,meta=fetch_sport_day("VOLLEYBALL",day)
                events.extend(ev);providers.append(meta);ok_any=True;day_calls+=int(meta.get("requests",0))
            except Exception as exc:
                providers.append({"sport":"VOLLEYBALL","status":"FAIL","error":str(exc)[:300]})
        else:
            for sport in SPORTS:
                if time.monotonic()-started>=max_seconds:break
                try:
                    ev,meta=fetch_sport_day(sport,day);events.extend(ev);providers.append(meta);ok_any=True;day_calls+=int(meta.get("requests",0))
                except Exception as exc:
                    providers.append({"sport":sport,"status":"FAIL","error":str(exc)[:300]})
                time.sleep(sleep_seconds)
        calls+=day_calls
        if not ok_any:break
        events.sort(key=lambda e:(e.get("start_timestamp",0),e.get("sport",""),e.get("id","")))
        payload={"date":day,"domain":"SPORTS","enabled_sports":list(SPORTS),"providers":providers,"events":events,"generated_at":datetime.now(KST).isoformat()}
        (HIST/f"{day}.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        saved+=1;days+=1;cur-=timedelta(days=1)
        s["cursor_date"]=cur.isoformat();s["days_saved"]=int(s.get("days_saved",0))+1;s["calls_total"]=int(s.get("calls_total",0))+day_calls
        if s.get("repair_replay") and s.get("repair_until"):
            try:
                if date.fromisoformat(day)<=date.fromisoformat(s["repair_until"]):
                    s["repair_replay"]=False
                    s.pop("repair_until",None)
            except Exception:
                pass
        save_state(s)
    if cur<START:s["complete"]=True
    s["revision"]=REVISION
    if cur<START:
        s["repair_replay"]=False
        s.pop("repair_until",None)
    save_state(s)
    print(json.dumps({"SPORTS_BACKFILL":"PASS","days_this_run":days,"files_saved":saved,"calls_this_run":calls,"cursor_date":s["cursor_date"],"complete":s.get("complete",False)},ensure_ascii=False))

def self_test():
    assert START.isoformat()=="2022-01-01"
    assert REVISION=="SPORTS_BACKFILL_V2_KOVO_REPAIR"
    print(json.dumps({"SPORTS_BACKFILL_SELF_TEST":"PASS","start":START.isoformat(),"revision":REVISION},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--max-days",type=int,default=30);ap.add_argument("--max-seconds",type=int,default=900);ap.add_argument("--sleep-seconds",type=float,default=.25);ap.add_argument("--self-test",action="store_true");a=ap.parse_args()
    if a.self_test:return self_test()
    run(a.max_days,a.max_seconds,a.sleep_seconds)
if __name__=="__main__":main()
