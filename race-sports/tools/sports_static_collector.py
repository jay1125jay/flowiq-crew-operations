#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from datetime import datetime
from sports_provider import KST, SPORTS, fetch_sport_day

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"sports_today.json"

def load_prev():
    if not OUT.exists():return None
    try:return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:return None

def stale_copy(e,reason):
    x=json.loads(json.dumps(e,ensure_ascii=False))
    x["stale"]=True;x["data_state"]="STALE_LAST_KNOWN_GOOD";x["stale_reason"]=reason
    return x

ODDS_FIELDS=("odds","odds_source","odds_provider","odds_capture_mode","odds_updated_at","bookmaker_odds")

def valid_odds(o):
    try:return float(o.get("odds") or 0)>1
    except Exception:return False

def merge_same_day_odds(events,prev):
    if not prev:return events
    old_map={e.get("id"):e for e in prev.get("events",[]) if e.get("id")}
    for e in events:
        old=old_map.get(e.get("id"))
        if not old:continue
        old_out={o.get("key"):o for o in old.get("outcomes",[]) if o.get("key")}
        copied=0
        for o in e.get("outcomes",[]):
            if valid_odds(o):
                o["odds_data_state"]="FRESH"
                continue
            po=old_out.get(o.get("key"))
            if not po or not valid_odds(po):continue
            for k in ODDS_FIELDS:
                if po.get(k) is not None:o[k]=json.loads(json.dumps(po[k],ensure_ascii=False))
            o["odds_data_state"]="PRESERVED_SAME_DAY"
            copied+=1
        if copied:
            e["odds_data_state"]="PRESERVED_SAME_DAY"
            e["odds_preserved_from"]=prev.get("generated_at")
    return events

def collect(day=None):
    now=datetime.now(KST);day=day or now.date().isoformat()
    prev=load_prev();prev=prev if prev and prev.get("date")==day else None
    old={}
    for e in (prev or {}).get("events",[]):old.setdefault(e.get("sport"),[]).append(e)
    providers=[];events=[]
    for sport in SPORTS:
        try:
            got,meta=fetch_sport_day(sport,day,include_odds=True)
            if prev and meta.get("status")=="PARTIAL":
                got_ids={e.get("id") for e in got}
                got.extend(stale_copy(e,"PROVIDER_PARTIAL_MISSING_EVENT") for e in old.get(sport,[]) if e.get("id") not in got_ids)
            events.extend(got)
            providers.append({
                "provider":f"SPORTS_{sport}_{meta.get('provider','SOURCE')}",
                "sport":sport,
                "status":meta["status"],
                "requests":meta["requests"],
                "successful_requests":meta["successful_requests"],
                "raw_events":meta["raw_events"],
                "top_tier_events":meta["top_tier_events"],
                "odds_events":int(meta.get("odds_events",0)),
                "odds_summary_requests":int(meta.get("odds_summary_requests",0)),
                "failures":meta["failures"],
            })
        except Exception as exc:
            recovered=[stale_copy(e,"PROVIDER_FETCH_FAILED") for e in old.get(sport,[])]
            events.extend(recovered)
            providers.append({"provider":f"SPORTS_{sport}_SOURCE","sport":sport,"status":"FAIL","error":str(exc)[:500],"recovered_events":len(recovered)})
    uniq={e.get("id"):e for e in events if e.get("id")}
    events=merge_same_day_odds(list(uniq.values()),prev)
    events.sort(key=lambda e:(e.get("start_timestamp",0),e.get("sport",""),e.get("id","")))
    payload={
        "date":day,"time":now.strftime("%H:%M:%S"),"generated_at":now.isoformat(),
        "domain":"SPORTS","source_contract":"CONFIGURED_TOP_TIER_SOURCE_LABELED",
        "enabled_sports":list(SPORTS),"providers":providers,"events":events,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix(".json.tmp");tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8");tmp.replace(OUT)
    return payload

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--date");a=ap.parse_args()
    p=collect(a.date)
    print(json.dumps({"SPORTS_COLLECT":"PASS","date":p["date"],"events":len(p["events"]),"by_sport":{s:sum(1 for e in p["events"] if e.get("sport")==s) for s in SPORTS},"providers":p["providers"]},ensure_ascii=False))
if __name__=="__main__":main()
