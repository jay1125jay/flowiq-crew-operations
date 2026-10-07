#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, re
from pathlib import Path
from sports_snapshot_finalize import normalize_multibook

ALLOWED={"SOCCER","BASEBALL","BASKETBALL","VOLLEYBALL"}
STATUSES={"SCHEDULED","LIVE","FINAL","POSTPONED","CANCELLED","SUSPENDED"}

def validate(path: Path):
    p=json.loads(path.read_text(encoding="utf-8"))
    multibook_status=normalize_multibook(p)
    p.setdefault("integrity",{})["sports_multibook_status"]=multibook_status
    path.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding="utf-8")

    assert p.get("domain")=="SPORTS","BAD_DOMAIN"
    assert set(p.get("enabled_sports",[]))==ALLOWED,"BAD_ENABLED_SPORTS"
    ids=set()
    stale=[]
    for e in p.get("events",[]):
        assert e.get("id") not in ids,"DUPLICATE_ID:"+str(e.get("id"))
        ids.add(e.get("id"))
        assert e.get("sport") in ALLOWED,"BAD_SPORT"
        assert e.get("tier")=="TOP","NON_TOP_TIER"
        assert e.get("status") in STATUSES,"BAD_STATUS"
        assert e.get("home") and e.get("away"),"MISSING_TEAMS"
        if e.get("stale") or e.get("data_state")=="STALE_LAST_KNOWN_GOOD":
            stale.append(e.get("id"))
        event_date=str(e.get("event_date") or "")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}",event_date),"BAD_EVENT_DATE"
        start=str(e.get("start_time") or "").strip()
        label=str(e.get("start_label") or "").strip()
        assert start not in {"--:--","시간 미정","TBD"},"TIME_PLACEHOLDER_FORBIDDEN"
        if start:
            assert re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",start),"BAD_START_TIME"
        else:
            assert label and label not in {"--:--","시간 미정","TBD"},"MISSING_DATE_FALLBACK"
        keys=[o.get("key") for o in e.get("outcomes",[])]
        if e["sport"]=="SOCCER":
            assert keys==["HOME","DRAW","AWAY"],"SOCCER_OUTCOMES"
        else:
            assert keys==["HOME","AWAY"],"BINARY_OUTCOMES"
        numeric_odds=[o for o in e.get("outcomes",[]) if isinstance(o.get("odds"),(int,float))]
        if numeric_odds:
            assert len(numeric_odds)==len(e.get("outcomes",[])),"PARTIAL_ODDS_DISTRIBUTION"
            for o in numeric_odds:
                assert math.isfinite(float(o["odds"])) and float(o["odds"])>1,"BAD_ODDS"
                assert o.get("odds_source"),"ODDS_SOURCE_MISSING"
                assert o.get("odds_provider"),"ODDS_PROVIDER_MISSING"
                assert o.get("odds_capture_mode"),"ODDS_MODE_MISSING"
                state=o.get("odds_data_state")
                assert state in {None,"FRESH","PRESERVED_SAME_DAY"},"BAD_ODDS_STATE"
        probs=[float(o["model_p"]) for o in e.get("outcomes",[]) if isinstance(o.get("model_p"),(int,float))]
        if probs:
            assert len(probs)==len(e.get("outcomes",[])),"PARTIAL_MODEL_DISTRIBUTION"
            assert all(0<=x<=1 for x in probs),"BAD_MODEL_PROB"
            assert abs(sum(probs)-1.0)<1e-5,"MODEL_SUM"
        if e.get("status")=="FINAL" and e.get("result"):
            r=e["result"]
            assert "home_score" in r and "away_score" in r,"FINAL_SCORE_MISSING"
        assert e.get("provider"),"PROVIDER_MISSING"
        assert e.get("source_url"),"SOURCE_URL_MISSING"

    assert not stale,"STALE_EVENTS_FORBIDDEN:"+str(stale[:5])
    hard=[(x.get("provider"),x.get("status")) for x in p.get("providers",[]) if x.get("status") in {"FAIL","ERROR","STALE_RECOVERED","RECOVERED"}]
    assert not hard,"HARD_PROVIDER_STATE:"+str(hard[:5])

    top3=p.get("sports_top3")
    if isinstance(top3,dict):
        assert top3.get("date")==p.get("date"),"TOP3_DATE_MISMATCH"
        seen=set()
        by_sport=top3.get("by_sport") or {}
        for sport in ALLOWED:
            rows=by_sport.get(sport) or []
            assert len(rows)<=3,"TOP3_TOO_MANY:"+sport
            for row in rows:
                eid=row.get("event_id")
                assert eid in ids,"TOP3_EVENT_MISSING:"+str(eid)
                assert eid not in seen,"TOP3_DUPLICATE_EVENT:"+str(eid)
                seen.add(eid)
                event=next(e for e in p.get("events",[]) if e.get("id")==eid)
                assert not event.get("stale"),"TOP3_STALE_EVENT:"+str(eid)

    print(json.dumps({"SPORTS_SNAPSHOT_VALIDATION":"PASS","events":len(p.get("events",[])),"stale_events":0,"top3_present":isinstance(top3,dict),"multibook_status":multibook_status},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("path",nargs="?",default="race-sports/data/sports_today.json")
    a=ap.parse_args()
    validate(Path(a.path))

if __name__=="__main__":main()
