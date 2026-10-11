#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "sports_today.json"
LOCK_FILE = ROOT / "data" / "model_state" / "sports_top3_lock.json"
SPORTS = ("SOCCER", "BASEBALL", "BASKETBALL", "VOLLEYBALL")
VERSION = "SPORTS_TOP3_V3_HIGH_PRECISION"

# Precision-first abstention gates. These do not claim a guaranteed future hit rate;
# they deliberately trade pick volume for stronger model separation.
MIN_TOP_P = {
    "SOCCER": 0.58,
    "BASEBALL": 0.62,
    "BASKETBALL": 0.70,
    "VOLLEYBALL": 0.70,
}
MIN_MARGIN = {
    "SOCCER": 0.12,
    "BASEBALL": 0.15,
    "BASKETBALL": 0.20,
    "VOLLEYBALL": 0.20,
}
MIN_COMP_GAMES = 100
MIN_TEAM_GAMES = 10


def _f(v, default=None):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _model_rows(event: dict):
    rows = []
    for o in event.get("outcomes", []) or []:
        p = _f(o.get("model_p"))
        key = str(o.get("key") or "")
        if key and p is not None and p > 0:
            rows.append((key, p))
    return sorted(rows, key=lambda x: x[1], reverse=True)


def _history_ok(event: dict) -> bool:
    h = event.get("model_history_scope") or {}
    comp = int(h.get("competition_games") or 0)
    home = int(h.get("home_team_games") or 0)
    away = int(h.get("away_team_games") or 0)
    return comp >= MIN_COMP_GAMES and min(home, away) >= MIN_TEAM_GAMES


def qualify(entry: dict, event: dict | None):
    if not event:
        return False, "EVENT_NOT_IN_CURRENT_SNAPSHOT", None
    sport = str(event.get("sport") or entry.get("sport") or "")
    if sport not in SPORTS:
        return False, "UNSUPPORTED_SPORT", None
    if event.get("model_validated") is not True or event.get("model_state") != "VALIDATED_HOLDOUT":
        return False, "MODEL_NOT_VALIDATED", None
    if event.get("stale") or event.get("data_state") == "STALE_LAST_KNOWN_GOOD":
        return False, "STALE_DATA", None
    rows = _model_rows(event)
    if len(rows) < 2:
        return False, "INCOMPLETE_MODEL_DISTRIBUTION", None

    top_key, top_p = rows[0]
    second_p = rows[1][1]
    margin = top_p - second_p
    if str(entry.get("pick_key")) != top_key:
        return False, "NOT_MODEL_TOP_PICK", {"top_key": top_key, "top_p": top_p, "margin": margin}
    if top_p < MIN_TOP_P[sport]:
        return False, "TOP_PROBABILITY_BELOW_PRECISION_GATE", {"top_key": top_key, "top_p": top_p, "margin": margin}
    if margin < MIN_MARGIN[sport]:
        return False, "MODEL_MARGIN_BELOW_PRECISION_GATE", {"top_key": top_key, "top_p": top_p, "margin": margin}
    if not _history_ok(event):
        return False, "INSUFFICIENT_HISTORY", {"top_key": top_key, "top_p": top_p, "margin": margin}
    return True, "PASS", {"top_key": top_key, "top_p": top_p, "margin": margin}


def apply(snapshot: dict, lock: dict | None):
    board = snapshot.get("sports_top3")
    if not isinstance(board, dict):
        raise SystemExit("SPORTS_TOP3_MISSING")
    events = {str(e.get("id")): e for e in snapshot.get("events", []) if e.get("id")}
    lock = lock if isinstance(lock, dict) else None

    rejected = []
    counts = {}
    for sport in SPORTS:
        source = list((board.get("by_sport") or {}).get(sport) or [])
        kept = []
        kept_ids = set()
        for row in source:
            eid = str(row.get("event_id") or "")
            ok, reason, metrics = qualify(row, events.get(eid))
            if not ok:
                rejected.append({"event_id": eid, "sport": sport, "reason": reason, "metrics": metrics})
                continue
            x = dict(row)
            x["rank"] = len(kept) + 1
            x["pick_basis"] = "MODEL_HIGH_CONFIDENCE"
            x["selection_type"] = "HIT_RATE"
            x["confidence"] = "HIGH_PRECISION"
            x["precision_gate"] = {
                "top_p": round(metrics["top_p"], 8),
                "margin": round(metrics["margin"], 8),
                "min_top_p": MIN_TOP_P[sport],
                "min_margin": MIN_MARGIN[sport],
            }
            kept.append(x)
            kept_ids.add(eid)
        board.setdefault("by_sport", {})[sport] = kept
        counts[sport] = len(kept)

        if lock is not None:
            lb = lock.setdefault("by_sport", {})
            lb[sport] = [x for x in (lb.get(sport) or []) if str(x.get("event_id") or "") in kept_ids]
            for i, x in enumerate(lb[sport], 1):
                x["rank"] = i

    board["version"] = VERSION
    board["selection_state"] = "HIGH_PRECISION_ABSTENTION"
    board["policy"] = (
        "MAX_3_PER_SPORT; MODEL_TOP_PICK_ONLY; VALIDATED_FRESH_ONLY; "
        "SPORT_SPECIFIC_PROBABILITY_AND_MARGIN_GATES; MIN_HISTORY; NO_FORCED_FILL; "
        "VALUE_AND_UPSET_EXCLUDED_FROM_HIT_RATE_BOARD"
    )
    board["precision_thresholds"] = {
        "min_top_p": MIN_TOP_P,
        "min_margin": MIN_MARGIN,
        "min_competition_games": MIN_COMP_GAMES,
        "min_team_games_each": MIN_TEAM_GAMES,
    }
    board["counts"] = counts
    board["rejected_count"] = len(rejected)
    board["rejected_reason_counts"] = {}
    for r in rejected:
        reason = r["reason"]
        board["rejected_reason_counts"][reason] = board["rejected_reason_counts"].get(reason, 0) + 1
    snapshot["sports_top3"] = board
    return snapshot, lock, rejected


def run(snapshot_path: Path = SNAPSHOT, lock_path: Path = LOCK_FILE):
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else None
    snapshot, lock, rejected = apply(snapshot, lock)
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    if lock is not None:
        lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "SPORTS_TOP3_PRECISION_GUARD": "PASS",
        "version": VERSION,
        "counts": snapshot["sports_top3"]["counts"],
        "rejected": len(rejected),
        "reasons": snapshot["sports_top3"]["rejected_reason_counts"],
    }, ensure_ascii=False))


def self_test():
    def ev(eid, sport, p, q, pick="HOME", comp=300, team=30):
        return {
            "id": eid, "sport": sport, "status": "SCHEDULED", "data_state": "FRESH",
            "model_validated": True, "model_state": "VALIDATED_HOLDOUT",
            "model_history_scope": {"competition_games": comp, "home_team_games": team, "away_team_games": team},
            "outcomes": [{"key": "HOME", "model_p": p}, {"key": "AWAY", "model_p": q}],
        }
    snap = {
        "events": [ev("GOOD", "BASKETBALL", .76, .24), ev("WEAK", "BASKETBALL", .58, .42), ev("UPSET", "BASEBALL", .70, .30)],
        "sports_top3": {"by_sport": {
            "SOCCER": [], "BASEBALL": [{"event_id": "UPSET", "sport": "BASEBALL", "pick_key": "AWAY"}],
            "BASKETBALL": [{"event_id": "GOOD", "sport": "BASKETBALL", "pick_key": "HOME"}, {"event_id": "WEAK", "sport": "BASKETBALL", "pick_key": "HOME"}],
            "VOLLEYBALL": []}, "counts": {}},
    }
    lock = {"by_sport": {s: list((snap["sports_top3"]["by_sport"]).get(s, [])) for s in SPORTS}}
    out, lock, rejected = apply(snap, lock)
    assert out["sports_top3"]["counts"]["BASKETBALL"] == 1
    assert out["sports_top3"]["by_sport"]["BASKETBALL"][0]["event_id"] == "GOOD"
    assert out["sports_top3"]["counts"]["BASEBALL"] == 0
    assert len(rejected) == 2
    print("SPORTS_TOP3_PRECISION_GUARD_SELF_TEST=PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        run()


if __name__ == "__main__":
    main()
