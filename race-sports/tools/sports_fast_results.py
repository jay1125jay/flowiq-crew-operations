#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sports_provider import SPORTS, fetch_sport_day

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "sports_today.json"
KST = timezone(timedelta(hours=9))
VERSION = "SPORTS_FAST_RESULTS_V1_RESULT_ONLY"
TERMINAL = {"FINAL", "POSTPONED", "CANCELLED"}
FORWARD = {"SCHEDULED": 0, "LIVE": 1, "FINAL": 2}


def _winner(event: dict):
    result = event.get("result") or {}
    wk = result.get("winner_key")
    if wk in {"HOME", "AWAY", "DRAW"}:
        return wk
    try:
        hs = float(result["home_score"])
        aw = float(result["away_score"])
    except Exception:
        return None
    if hs > aw:
        return "HOME"
    if aw > hs:
        return "AWAY"
    return "DRAW" if event.get("sport") == "SOCCER" else None


def due_sports(snapshot: dict, now: datetime) -> list[str]:
    now_ts = int(now.timestamp())
    due = set()
    for e in snapshot.get("events", []) or []:
        sport = str(e.get("sport") or "")
        status = str(e.get("status") or "").upper()
        if sport not in SPORTS or status in TERMINAL:
            continue
        if status == "LIVE":
            due.add(sport)
            continue
        try:
            start_ts = int(e.get("start_timestamp"))
        except Exception:
            continue
        # Poll shortly before start and keep polling overdue scheduled rows.
        if start_ts <= now_ts + 15 * 60:
            due.add(sport)
    return [s for s in SPORTS if s in due]


def _merge_event(target: dict, source: dict) -> int:
    changed = 0
    old_status = str(target.get("status") or "SCHEDULED").upper()
    new_status = str(source.get("status") or "").upper()

    if new_status in {"POSTPONED", "CANCELLED"}:
        if target.get("status") != new_status:
            target["status"] = new_status
            changed += 1
        if "score" in target:
            target.pop("score", None)
            changed += 1
        return changed

    if new_status == "FINAL":
        wk = _winner(source)
        if not wk:
            return changed
        if target.get("status") != "FINAL":
            target["status"] = "FINAL"
            changed += 1
        result = deepcopy(source.get("result") or {})
        if target.get("result") != result:
            target["result"] = result
            changed += 1
        if "score" in target:
            target.pop("score", None)
            changed += 1
        return changed

    if new_status == "LIVE" and FORWARD.get(old_status, 0) < FORWARD["LIVE"]:
        target["status"] = "LIVE"
        changed += 1
    if new_status == "LIVE" and isinstance(source.get("score"), dict):
        score = deepcopy(source["score"])
        if target.get("score") != score:
            target["score"] = score
            changed += 1
    # Never downgrade LIVE/FINAL to SCHEDULED and never copy odds/model fields.
    return changed


def refresh(snapshot: dict, now: datetime | None = None, fetcher=fetch_sport_day):
    now = now or datetime.now(KST)
    day = str(snapshot.get("date") or now.date().isoformat())
    sports = due_sports(snapshot, now)
    events = {str(e.get("id")): e for e in snapshot.get("events", []) or [] if e.get("id")}
    changed = 0
    meta = []

    for sport in sports:
        try:
            rows, provider_meta = fetcher(sport, day, include_odds=False)
            src = {str(e.get("id")): e for e in rows if e.get("id")}
            matched = 0
            sport_changed = 0
            for eid, target in events.items():
                if target.get("sport") != sport or str(target.get("status") or "").upper() in TERMINAL:
                    continue
                source = src.get(eid)
                if not source:
                    continue
                matched += 1
                n = _merge_event(target, source)
                changed += n
                sport_changed += n
            meta.append({"sport": sport, "status": "PASS", "matched": matched, "field_changes": sport_changed, "provider": provider_meta.get("provider")})
        except Exception as exc:
            meta.append({"sport": sport, "status": "DEGRADED", "error": str(exc)[:300]})

    snapshot["fast_results"] = {
        "version": VERSION,
        "updated_at": now.isoformat(timespec="seconds"),
        "polled_sports": sports,
        "field_changes": changed,
        "providers": meta,
        "policy": "RESULT_ONLY_DELTA; CURRENT_EVENT_IDS_ONLY; NO_EVENT_INSERT; NO_ODDS_OR_MODEL_MUTATION; NO_STATUS_DOWNGRADE",
    }
    return snapshot, changed


def run(path: Path = SNAPSHOT):
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    out, changed = refresh(snapshot)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"SPORTS_FAST_RESULTS": "PASS", "changed": changed, "polled_sports": out["fast_results"]["polled_sports"], "providers": out["fast_results"]["providers"]}, ensure_ascii=False))


def self_test():
    now = datetime(2026, 10, 12, 20, 0, tzinfo=KST)
    snap = {"date": "2026-10-12", "events": [
        {"id": "B1", "sport": "BASKETBALL", "status": "SCHEDULED", "start_timestamp": int((now-timedelta(hours=1)).timestamp()), "outcomes": [{"key": "HOME", "model_p": .7}, {"key": "AWAY", "model_p": .3}]},
        {"id": "B2", "sport": "BASKETBALL", "status": "FINAL", "start_timestamp": int((now-timedelta(hours=4)).timestamp()), "result": {"winner_key": "HOME"}},
        {"id": "S1", "sport": "SOCCER", "status": "SCHEDULED", "start_timestamp": int((now+timedelta(hours=3)).timestamp())},
    ]}

    def fake(sport, day, include_odds=False):
        assert include_odds is False
        if sport == "BASKETBALL":
            return [
                {"id": "B1", "sport": "BASKETBALL", "status": "FINAL", "result": {"winner_key": "AWAY", "home_score": 90, "away_score": 95}, "outcomes": [{"key": "HOME", "odds": 9.99}]},
                {"id": "NEW", "sport": "BASKETBALL", "status": "FINAL", "result": {"winner_key": "HOME"}},
            ], {"provider": "TEST"}
        raise AssertionError("unexpected sport")

    out, changed = refresh(deepcopy(snap), now, fake)
    b1 = next(e for e in out["events"] if e["id"] == "B1")
    assert out["fast_results"]["polled_sports"] == ["BASKETBALL"]
    assert b1["status"] == "FINAL" and b1["result"]["winner_key"] == "AWAY"
    assert b1["outcomes"][0]["model_p"] == .7 and "odds" not in b1["outcomes"][0]
    assert all(e["id"] != "NEW" for e in out["events"])
    assert next(e for e in out["events"] if e["id"] == "B2")["result"]["winner_key"] == "HOME"
    assert changed >= 2
    print("SPORTS_FAST_RESULTS_SELF_TEST=PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    self_test() if args.self_test else run()


if __name__ == "__main__":
    main()
