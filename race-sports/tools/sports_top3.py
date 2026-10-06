#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "sports_today.json"
LOCK_FILE = ROOT / "data" / "model_state" / "sports_top3_lock.json"
KST = timezone(timedelta(hours=9))
SPORTS = ("SOCCER", "BASEBALL", "BASKETBALL", "VOLLEYBALL")
VERSION = "SPORTS_TOP3_V2_EDGE_GATED_DAILY_LOCK"
VALUE_EDGE_MIN = 0.03
VALUE_EV_MIN = 0.05
UPSET_EDGE_MIN = 0.05
UPSET_EV_MIN = 0.08


def _f(v, default=None):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, float(v)))


def _fresh(e: dict) -> bool:
    return not e.get("stale") and e.get("data_state") != "STALE_LAST_KNOWN_GOOD"


def _winner_key(e: dict):
    r = e.get("result") or {}
    wk = r.get("winner_key")
    if wk in {"HOME", "AWAY", "DRAW"}:
        return wk
    try:
        hs, aw = float(r["home_score"]), float(r["away_score"])
    except Exception:
        return None
    if hs > aw:
        return "HOME"
    if aw > hs:
        return "AWAY"
    return "DRAW" if e.get("sport") == "SOCCER" else None


def _pick_name(e: dict, key: str, fallback: str = "") -> str:
    if key == "HOME":
        return str(e.get("home_ko") or e.get("home") or fallback or "HOME")
    if key == "AWAY":
        return str(e.get("away_ko") or e.get("away") or fallback or "AWAY")
    if key == "DRAW":
        return "무승부"
    return str(fallback or key)


def _model_rows(e: dict):
    rows = []
    for o in e.get("outcomes", []):
        p = _f(o.get("model_p"))
        if p is not None and p > 0:
            rows.append((str(o.get("key")), p, o))
    return sorted(rows, key=lambda x: x[1], reverse=True)


def _market_rows(e: dict) -> dict[str, dict]:
    decision = e.get("market_decision") if isinstance(e.get("market_decision"), dict) else {}
    direct = {}
    for row in decision.get("market", []) or []:
        if row.get("key"):
            direct[str(row["key"])] = dict(row)
    if direct:
        return direct

    odds_rows = []
    for o in e.get("outcomes", []):
        odds = _f(o.get("odds"))
        state = str(o.get("odds_data_state") or "FRESH")
        if odds and odds > 1 and state != "PRESERVED_SAME_DAY":
            odds_rows.append((str(o.get("key")), odds, o))
    if len(odds_rows) < 2:
        return {}
    inv = [1.0 / x[1] for x in odds_rows]
    z = sum(inv)
    if z <= 0:
        return {}
    out = {}
    for i, (key, odds, o) in enumerate(odds_rows):
        mp = inv[i] / z
        model_p = _f(o.get("model_p"))
        out[key] = {
            "key": key,
            "odds": odds,
            "market_p": mp,
            "model_p": model_p,
            "edge": (model_p - mp) if model_p is not None else None,
            "ev": (model_p * odds - 1.0) if model_p is not None else None,
            "odds_provider": o.get("odds_provider") or e.get("odds_provider"),
        }
    return out


def _qualifying_market_pick(e: dict, rows: list, market: dict[str, dict]):
    if not market:
        return None
    model_map = {k: p for k, p, _ in rows}
    usable = {k: v for k, v in market.items() if k in model_map and _f(v.get("market_p")) is not None}
    if len(usable) < 2:
        return None
    favorite = max(usable, key=lambda k: _f(usable[k].get("market_p"), 0.0))

    decision = e.get("market_decision") if isinstance(e.get("market_decision"), dict) else {}
    primary = decision.get("primary_pick") if isinstance(decision.get("primary_pick"), dict) else None
    ordered_keys = []
    if primary and str(primary.get("key")) in usable:
        ordered_keys.append(str(primary["key"]))
    ordered_keys.extend(k for k in model_map if k not in ordered_keys)

    qualified = []
    for key in ordered_keys:
        mr = usable.get(key) or {}
        edge = _f(mr.get("edge"))
        ev = _f(mr.get("ev"))
        if edge is None or ev is None:
            continue
        is_upset = key != favorite
        if is_upset and edge >= UPSET_EDGE_MIN and ev >= UPSET_EV_MIN:
            kind = "UPSET"
            priority = 2
        elif edge >= VALUE_EDGE_MIN and ev >= VALUE_EV_MIN:
            kind = "VALUE"
            priority = 1
        else:
            continue
        qualified.append((priority, edge, ev, model_map[key], key, kind))

    if not qualified:
        return None
    qualified.sort(reverse=True)
    _, _, _, _, key, kind = qualified[0]
    return key, kind


def _candidate(e: dict):
    if e.get("sport") not in SPORTS:
        return None
    if e.get("status") != "SCHEDULED" or not _fresh(e):
        return None
    if e.get("model_validated") is not True or e.get("model_state") != "VALIDATED_HOLDOUT":
        return None
    rows = _model_rows(e)
    if len(rows) < 2:
        return None

    market = _market_rows(e)
    market_pick = _qualifying_market_pick(e, rows, market)
    if market:
        if not market_pick:
            return None
        pick_key, selection_type = market_pick
        basis = "MARKET_EDGE"
    else:
        pick_key = rows[0][0]
        selection_type = "AI_ONLY"
        basis = "AI_ONLY_NO_ODDS"

    model_map = {k: p for k, p, _ in rows}
    model_p = model_map[pick_key]
    n = len(rows)
    baseline = 1.0 / n
    prob_strength = _clamp((model_p - baseline) / max(1e-9, 1.0 - baseline))
    ai_top_p = rows[0][1]
    ai_second_p = rows[1][1]
    separation_strength = _clamp((ai_top_p - ai_second_p) / 0.25)

    scope = e.get("model_history_scope") or {}
    comp_games = int(scope.get("competition_games") or 0)
    home_games = int(scope.get("home_team_games") or 0)
    away_games = int(scope.get("away_team_games") or 0)
    history_strength = 0.6 * _clamp(comp_games / 500.0) + 0.4 * _clamp(min(home_games, away_games) / 30.0)

    mr = market.get(pick_key) or {}
    odds = _f(mr.get("odds"))
    market_p = _f(mr.get("market_p"))
    edge = _f(mr.get("edge"))
    ev = _f(mr.get("ev"))
    market_strength = 0.0
    if edge is not None:
        market_strength += 0.6 * _clamp(max(edge, 0.0) / 0.10)
    if ev is not None:
        market_strength += 0.4 * _clamp(max(ev, 0.0) / 0.15)

    if basis == "MARKET_EDGE":
        score = 100.0 * (0.35 * prob_strength + 0.20 * history_strength + 0.45 * market_strength)
        if selection_type == "UPSET":
            score += 4.0
    else:
        score = 100.0 * (0.55 * prob_strength + 0.20 * separation_strength + 0.25 * history_strength)

    confidence = "HIGH" if score >= 70 else "MEDIUM" if score >= 52 else "WATCH"
    return {
        "event_id": e.get("id"),
        "sport": e.get("sport"),
        "competition": e.get("competition"),
        "event_date": e.get("event_date"),
        "start_time": e.get("start_time"),
        "start_label": e.get("start_label"),
        "start_timestamp": e.get("start_timestamp"),
        "title": e.get("title") or f"{e.get('home')} vs {e.get('away')}",
        "home": e.get("home"),
        "away": e.get("away"),
        "home_ko": e.get("home_ko"),
        "away_ko": e.get("away_ko"),
        "pick_key": pick_key,
        "pick_name": _pick_name(e, pick_key),
        "pick_basis": basis,
        "selection_type": selection_type,
        "model_p": round(model_p, 8),
        "odds": round(odds, 6) if odds is not None else None,
        "market_p": round(market_p, 8) if market_p is not None else None,
        "edge": round(edge, 8) if edge is not None else None,
        "ev": round(ev, 8) if ev is not None else None,
        "odds_provider": mr.get("odds_provider"),
        "history": {
            "competition_games": comp_games,
            "home_team_games": home_games,
            "away_team_games": away_games,
        },
        "selection_score": round(score, 3),
        "confidence": confidence,
        "status": e.get("status"),
    }


def _refresh_locked(entry: dict, event: dict | None):
    x = dict(entry)
    if event is None:
        x["current_state"] = "MISSING_CURRENT_SNAPSHOT"
        return x
    x["status"] = event.get("status")
    x["current_state"] = "FRESH" if _fresh(event) else "STALE"
    x["result"] = event.get("result")
    wk = _winner_key(event)
    if event.get("status") == "FINAL" and wk:
        x["evaluation"] = {"winner_key": wk, "hit": wk == x.get("pick_key")}
    return x


def build(snapshot: dict, lock: dict | None = None, now: datetime | None = None):
    now = now or datetime.now(KST)
    day = str(snapshot.get("date") or now.date().isoformat())
    if not lock or lock.get("date") != day or lock.get("version") != VERSION:
        lock = {"version": VERSION, "date": day, "by_sport": {s: [] for s in SPORTS}}

    events = {e.get("id"): e for e in snapshot.get("events", []) if e.get("id")}
    by_sport = lock.setdefault("by_sport", {})
    now_iso = now.isoformat(timespec="seconds")

    for sport in SPORTS:
        existing = [dict(x) for x in by_sport.get(sport, []) if x.get("event_id")][:3]
        used = {x["event_id"] for x in existing}
        candidates = []
        for e in snapshot.get("events", []):
            if e.get("sport") != sport or e.get("id") in used:
                continue
            c = _candidate(e)
            if c:
                candidates.append(c)
        candidates.sort(key=lambda x: (-float(x["selection_score"]), int(x.get("start_timestamp") or 0), str(x.get("event_id"))))
        while len(existing) < 3 and candidates:
            c = candidates.pop(0)
            c["locked_at"] = now_iso
            existing.append(c)
        for i, x in enumerate(existing, 1):
            x["rank"] = i
        by_sport[sport] = existing

    lock["updated_at"] = now_iso
    lock["policy"] = "MAX_3_PER_SPORT; KST_DATE_LOCK; SCHEDULED_FRESH_VALIDATED_ONLY; ODDS_PRESENT_REQUIRES_VALUE_OR_UPSET_EDGE; NO_ODDS_ALLOWS_AI_ONLY; NO_FORCED_FILL"

    public = {
        "version": VERSION,
        "date": day,
        "generated_at": now_iso,
        "selection_state": "LOCKED_FOR_KST_DATE",
        "policy": lock["policy"],
        "thresholds": {
            "value_edge_min": VALUE_EDGE_MIN,
            "value_ev_min": VALUE_EV_MIN,
            "upset_edge_min": UPSET_EDGE_MIN,
            "upset_ev_min": UPSET_EV_MIN,
        },
        "by_sport": {},
        "counts": {},
    }
    for sport in SPORTS:
        rows = [_refresh_locked(x, events.get(x.get("event_id"))) for x in by_sport.get(sport, [])]
        public["by_sport"][sport] = rows
        public["counts"][sport] = len(rows)
    return public, lock


def run(snapshot_path: Path = SNAPSHOT, lock_path: Path = LOCK_FILE):
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    lock = None
    if lock_path.exists():
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
        except Exception:
            lock = None
    public, lock = build(snapshot, lock)
    snapshot["sports_top3"] = public
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"SPORTS_TOP3": "PASS", "counts": public["counts"], "state": public["selection_state"]}, ensure_ascii=False))


def self_test():
    events = []
    for i in range(4):
        p = 0.61 + i * 0.03
        events.append({
            "id": f"E{i}", "sport": "BASKETBALL", "status": "SCHEDULED", "data_state": "FRESH",
            "competition": "NBA", "event_date": "2026-10-07", "start_time": f"1{i}:00", "start_timestamp": 100 + i,
            "title": f"H{i} vs A{i}", "home": f"H{i}", "away": f"A{i}",
            "model_validated": True, "model_state": "VALIDATED_HOLDOUT",
            "model_history_scope": {"competition_games": 500, "home_team_games": 30, "away_team_games": 30},
            "outcomes": [
                {"key": "HOME", "name": f"H{i}", "model_p": p, "odds": 1.8 + i * .1, "odds_data_state": "FRESH"},
                {"key": "AWAY", "name": f"A{i}", "model_p": 1-p, "odds": 2.1 + i * .1, "odds_data_state": "FRESH"},
            ],
        })
    snap = {"date": "2026-10-07", "events": events}
    now = datetime(2026, 10, 7, 7, 0, tzinfo=KST)
    public, lock = build(snap, None, now)
    rows = public["by_sport"]["BASKETBALL"]
    assert len(rows) == 3
    assert [x["rank"] for x in rows] == [1, 2, 3]
    locked_ids = [x["event_id"] for x in rows]
    snap["events"] = list(reversed(events))
    public2, lock2 = build(snap, lock, now + timedelta(minutes=30))
    assert [x["event_id"] for x in public2["by_sport"]["BASKETBALL"]] == locked_ids
    assert lock2["date"] == "2026-10-07"

    bad = dict(events[0])
    bad["id"] = "BAD"
    bad["outcomes"] = [
        {"key": "HOME", "name": "H", "model_p": 0.55, "odds": 1.05, "odds_data_state": "FRESH"},
        {"key": "AWAY", "name": "A", "model_p": 0.45, "odds": 8.0, "odds_data_state": "FRESH"},
    ]
    assert _candidate(bad) is None or _candidate(bad)["pick_key"] != "HOME"
    print(json.dumps({"SPORTS_TOP3_SELF_TEST": "PASS", "locked": locked_ids, "edge_gate": "PASS"}, ensure_ascii=False))


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
