#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from datetime import datetime
from sports_provider import KST, SPORTS, fetch_sport_day

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sports_today.json"

def load_prev():
    if not OUT.exists(): return None
    try: return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception: return None

def mark_stale(e: dict, reason: str) -> dict:
    x = json.loads(json.dumps(e, ensure_ascii=False))
    x["stale"] = True
    x["data_state"] = "STALE_LAST_KNOWN_GOOD"
    x["stale_reason"] = reason
    return x

def collect(day: str | None = None) -> dict:
    now = datetime.now(KST)
    day = day or now.date().isoformat()
    prev = load_prev()
    prev_same = prev if prev and prev.get("date") == day else None
    prev_by_sport = {}
    for e in (prev_same or {}).get("events",[]):
        prev_by_sport.setdefault(e.get("sport"),[]).append(e)
    providers, events = [], []
    for sport in SPORTS:
        try:
            got, meta = fetch_sport_day(sport, day)
            providers.append({
                "provider": f"SPORTS_{sport}_SOFASCORE",
                "sport": sport,
                "status": "PASS",
                "raw_events": meta["raw_events"],
                "top_tier_events": meta["top_tier_events"],
                "source_url": meta["source_url"],
            })
            events.extend(got)
        except Exception as exc:
            old = [mark_stale(e, "PROVIDER_FETCH_FAILED") for e in prev_by_sport.get(sport,[])]
            events.extend(old)
            providers.append({
                "provider": f"SPORTS_{sport}_SOFASCORE",
                "sport": sport,
                "status": "FAIL",
                "error": str(exc)[:500],
                "recovered_events": len(old),
            })
    events.sort(key=lambda e:(e.get("start_timestamp",0),e.get("sport",""),e.get("id","")))
    payload = {
        "date": day,
        "time": now.strftime("%H:%M:%S"),
        "generated_at": now.isoformat(),
        "domain": "SPORTS",
        "source_contract": "TOP_TIER_ONLY_SOURCE_LABELED",
        "enabled_sports": list(SPORTS),
        "providers": providers,
        "events": events,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(OUT)
    return payload

def self_test():
    p = collect("2026-10-04")
    assert p["domain"] == "SPORTS"
    assert p["enabled_sports"] == list(SPORTS)
    print(json.dumps({"SPORTS_COLLECTOR_SELF_TEST":"PASS","events":len(p["events"])},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    if a.self_test:
        from sports_provider import self_test as provider_self_test
        provider_self_test()
        return
    p=collect(a.date)
    print(json.dumps({
        "SPORTS_COLLECT":"PASS",
        "date":p["date"],
        "events":len(p["events"]),
        "by_sport":{s:sum(1 for e in p["events"] if e.get("sport")==s) for s in SPORTS},
        "providers":p["providers"],
    },ensure_ascii=False))

if __name__=="__main__":
    main()
