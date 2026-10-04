#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, re
from pathlib import Path

ALLOWED={"SOCCER","BASEBALL","BASKETBALL","VOLLEYBALL"}
STATUSES={"SCHEDULED","LIVE","FINAL","POSTPONED","CANCELLED","SUSPENDED"}

def validate(path: Path):
    p=json.loads(path.read_text(encoding="utf-8"))
    assert p.get("domain")=="SPORTS","BAD_DOMAIN"
    assert set(p.get("enabled_sports",[]))==ALLOWED,"BAD_ENABLED_SPORTS"
    ids=set()
    for e in p.get("events",[]):
        assert e.get("id") not in ids,"DUPLICATE_ID:"+str(e.get("id"))
        ids.add(e.get("id"))
        assert e.get("sport") in ALLOWED,"BAD_SPORT"
        assert e.get("tier")=="TOP","NON_TOP_TIER"
        assert e.get("status") in STATUSES,"BAD_STATUS"
        assert e.get("home") and e.get("away"),"MISSING_TEAMS"
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
                assert o.get("odds_data_state") in {"FRESH","PRESERVED_SAME_DAY"},"ODDS_STATE_MISSING"
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
    print(json.dumps({"SPORTS_SNAPSHOT_VALIDATION":"PASS","events":len(p.get("events",[]))},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("path",nargs="?",default="race-sports/data/sports_today.json")
    a=ap.parse_args()
    validate(Path(a.path))

if __name__=="__main__":main()
