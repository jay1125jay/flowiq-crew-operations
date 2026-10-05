#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RACING = ROOT / "data" / "today.json"
SPORTS = ROOT / "data" / "sports_today.json"
RACING_HISTORY = ROOT / "data" / "history"
SPORTS_HISTORY = ROOT / "data" / "sports_history"
VERSION = "market_edge_v1.0"

RACING_PRE_SOURCES = {
    "KBOAT_FINAL_SINGLE_AUTO",
    "KCYCLE_FINAL_SINGLE_AUTO",
    "KRA_FINAL_SINGLE_AUTO",
    "CPC_FINAL_SINGLE_AUTO",
}
KRA_PRE_SOURCES = {"KRA_API301_OFFICIAL", "KRA_API28_OFFICIAL"}
SPORTS_PRE_SOURCES = {"ESPN_PUBLIC_ODDS", "SPORTSGAMEODDS"}


def fnum(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def is_fresh(event):
    return not event.get("stale") and event.get("data_state") != "STALE_LAST_KNOWN_GOOD"


def provider_status(doc, name):
    for p in doc.get("providers", []):
        if p.get("provider") == name:
            return p.get("status")
    return None


def trusted_pre_odds(outcome):
    odd = fnum(outcome.get("odds"))
    if odd is None or odd <= 1.0:
        return False
    if str(outcome.get("odds_data_state") or "FRESH") == "PRESERVED_SAME_DAY":
        return False
    src = str(outcome.get("odds_source") or "")
    mode = str(outcome.get("odds_capture_mode") or "")
    if src in RACING_PRE_SOURCES:
        return mode == "PRE_RACE_OFFICIAL"
    if src in KRA_PRE_SOURCES:
        return mode == "PRE_RACE"
    if src == "ESPN_PUBLIC_ODDS":
        return mode == "PRE_GAME_SOURCE_LABELED"
    if src == "SPORTSGAMEODDS":
        return mode == "PRE_GAME_MULTI_BOOK"
    return False


def model_ready(doc, event):
    if not is_fresh(event):
        return False
    if event.get("model_validated") is True:
        return True
    state = str(event.get("model_state") or "")
    if state.startswith("VALIDATED"):
        return True
    sport = event.get("sport")
    if sport == "BULL":
        return provider_status(doc, "BULL_MODEL_V130") == "PASS"
    return False


def odds_quality(rows):
    sources = sorted({str(r["source"]) for r in rows if r.get("source")})
    if any(s == "SPORTSGAMEODDS" for s in sources):
        return "MULTI_BOOK", sources
    if any(s == "ESPN_PUBLIC_ODDS" for s in sources):
        return "SOURCE_LABELED", sources
    return "OFFICIAL", sources


def grade(edge, ev, model_p, odds):
    if edge >= 0.12 and ev >= 0.20 and model_p >= 0.20:
        return "A"
    if edge >= 0.08 and ev >= 0.12:
        return "B"
    return "C"


def risk_label(model_p, odds):
    if odds >= 8.0 or model_p < 0.15:
        return "EXTREME"
    if odds >= 5.0 or model_p < 0.22:
        return "HIGH"
    if odds >= 3.0:
        return "MEDIUM"
    return "NORMAL"


def public_pick(row):
    return {
        "key": row["key"],
        "name": row.get("name") or row["key"],
        "model_p": round(row["model_p"], 8),
        "market_p": round(row["market_p"], 8),
        "edge": round(row["edge"], 8),
        "odds": round(row["odds"], 4),
        "ev": round(row["ev"], 8),
        "market_rank": row["market_rank"],
        "is_underdog": row["is_underdog"],
        "grade": grade(row["edge"], row["ev"], row["model_p"], row["odds"]),
        "risk": risk_label(row["model_p"], row["odds"]),
        "odds_source": row.get("source"),
        "odds_capture_mode": row.get("capture_mode"),
    }


def score_event(doc, event):
    if event.get("status") != "SCHEDULED":
        return None, "NOT_SCHEDULED"
    if not model_ready(doc, event):
        return None, "MODEL_NOT_VALIDATED"

    modeled = []
    for o in event.get("outcomes", []):
        p = fnum(o.get("model_p"))
        if p is not None and p > 0:
            modeled.append(o)
    if len(modeled) < 2:
        return None, "MODEL_PROBABILITY_MISSING"

    rows = []
    for o in modeled:
        if not trusted_pre_odds(o):
            return None, "ODDS_INCOMPLETE"
        p = fnum(o.get("model_p"))
        d = fnum(o.get("odds"))
        rows.append({
            "key": str(o.get("key")),
            "name": str(o.get("name") or o.get("key")),
            "model_p": p,
            "odds": d,
            "raw_market": 1.0 / d,
            "source": str(o.get("odds_source") or ""),
            "capture_mode": str(o.get("odds_capture_mode") or ""),
        })

    inv_sum = sum(r["raw_market"] for r in rows)
    if inv_sum <= 0:
        return None, "MARKET_INVALID"
    market_order = sorted(rows, key=lambda r: r["raw_market"], reverse=True)
    rank = {r["key"]: i + 1 for i, r in enumerate(market_order)}
    favorite_key = market_order[0]["key"]

    for r in rows:
        r["market_p"] = r["raw_market"] / inv_sum
        r["edge"] = r["model_p"] - r["market_p"]
        r["ev"] = r["model_p"] * r["odds"] - 1.0
        r["market_rank"] = rank[r["key"]]
        r["is_underdog"] = r["key"] != favorite_key
        r["score"] = 0.70 * r["edge"] + 0.30 * min(max(r["ev"], -1.0), 1.5)

    model_top = max(rows, key=lambda r: r["model_p"])
    favorite = next(r for r in rows if r["key"] == favorite_key)
    values = [r for r in rows if r["edge"] >= 0.03 and r["ev"] >= 0.05]
    upsets = [r for r in values if r["is_underdog"] and r["edge"] >= 0.05 and r["ev"] >= 0.08]
    best_value = max(values, key=lambda r: (r["score"], r["edge"], r["ev"]), default=None)
    best_upset = max(upsets, key=lambda r: (r["score"], r["edge"], r["ev"]), default=None)
    primary = best_upset or best_value
    primary_type = "UPSET" if best_upset else "VALUE" if best_value else "NO_BET"
    quality, sources = odds_quality(rows)

    decision = {
        "version": VERSION,
        "state": "READY" if primary else "NO_VALUE",
        "primary_type": primary_type,
        "primary_pick": public_pick(primary) if primary else None,
        "upset_pick": public_pick(best_upset) if best_upset else None,
        "value_pick": public_pick(best_value) if best_value else None,
        "model_top": public_pick(model_top),
        "market_favorite": public_pick(favorite),
        "market_overround": round(inv_sum - 1.0, 8),
        "odds_quality": quality,
        "odds_sources": sources,
        "selection_rule": "UPSET_FIRST_THEN_VALUE; edge>=3pp ev>=5%; upset edge>=5pp ev>=8%",
        "market": [public_pick(r) for r in sorted(rows, key=lambda r: r["market_rank"])],
    }
    return decision, None


def actual_key(event):
    sport = event.get("sport")
    result = event.get("result") or {}
    if sport in {"SOCCER", "BASEBALL", "BASKETBALL", "VOLLEYBALL"}:
        key = result.get("winner_key")
        if key in {"HOME", "AWAY", "DRAW"}:
            return key
        try:
            h = float(result.get("home_score"))
            a = float(result.get("away_score"))
            if h > a:
                return "HOME"
            if a > h:
                return "AWAY"
            return "DRAW" if sport == "SOCCER" else None
        except Exception:
            return None
    if sport == "BULL":
        key = ((result.get("winner") or {}).get("key")) or result.get("winner_key")
        return key if key in {"RED", "DRAW", "BLUE"} else None
    for x in result.get("top3") or []:
        try:
            if int(x.get("rank")) == 1:
                return "N" + str(int(x.get("number")))
        except Exception:
            pass
    try:
        if result.get("winner_number") is not None:
            return "N" + str(int(result.get("winner_number")))
    except Exception:
        pass
    for o in event.get("outcomes", []):
        try:
            if int(o.get("final_rank")) == 1:
                return str(o.get("key"))
        except Exception:
            if o.get("won") is True:
                return str(o.get("key"))
    return None


def load_prior(path, event_id):
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    for e in d.get("events", []):
        if e.get("id") == event_id and isinstance(e.get("market_decision"), dict):
            return e.get("market_decision")
    return None


def evaluate(decision, event):
    if not decision:
        return decision
    key = actual_key(event)
    if not key:
        return decision
    out = dict(decision)
    ev = dict(out.get("evaluation") or {})
    ev["actual_key"] = key
    for field in ("primary_pick", "upset_pick", "value_pick"):
        pick = out.get(field)
        if not isinstance(pick, dict):
            continue
        hit = pick.get("key") == key
        ev[field + "_hit"] = hit
        ev[field + "_unit_return"] = round(float(pick.get("odds") or 0) - 1.0, 4) if hit else -1.0
    out["evaluation"] = ev
    return out


def enrich(path, history_dir):
    if not path.exists():
        return {"file": str(path), "status": "MISSING", "ready": 0, "upset": 0, "value": 0, "carried": 0}
    doc = json.loads(path.read_text(encoding="utf-8"))
    day = str(doc.get("date") or "")
    prior_path = history_dir / f"{day}.json" if day else Path("__missing__")
    ready = upset = value = carried = 0
    for e in doc.get("events", []):
        if e.get("status") == "SCHEDULED":
            decision, reason = score_event(doc, e)
            if decision:
                e["market_decision"] = decision
                ready += 1
                upset += 1 if decision.get("upset_pick") else 0
                value += 1 if decision.get("value_pick") else 0
            else:
                e["market_decision"] = {"version": VERSION, "state": reason or "UNAVAILABLE", "primary_type": "NO_BET"}
        elif e.get("status") == "FINAL":
            prior = e.get("market_decision") if isinstance(e.get("market_decision"), dict) else load_prior(prior_path, e.get("id"))
            if prior:
                e["market_decision"] = evaluate(prior, e)
                carried += 1
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    if day:
        history_dir.mkdir(parents=True, exist_ok=True)
        (history_dir / f"{day}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"file": str(path), "status": "PASS", "ready": ready, "upset": upset, "value": value, "carried": carried}


def self_test():
    doc = {"providers": [], "events": []}
    e = {
        "id": "TEST",
        "sport": "BASKETBALL",
        "status": "SCHEDULED",
        "model_validated": True,
        "outcomes": [
            {"key": "HOME", "name": "Favorite", "model_p": 0.58, "odds": 1.50, "odds_source": "ESPN_PUBLIC_ODDS", "odds_capture_mode": "PRE_GAME_SOURCE_LABELED"},
            {"key": "AWAY", "name": "Underdog", "model_p": 0.42, "odds": 3.50, "odds_source": "ESPN_PUBLIC_ODDS", "odds_capture_mode": "PRE_GAME_SOURCE_LABELED"},
        ],
    }
    d, err = score_event(doc, e)
    assert not err, err
    assert d["primary_type"] == "UPSET", d
    assert d["upset_pick"]["key"] == "AWAY", d
    assert d["upset_pick"]["edge"] > 0.10, d
    assert d["upset_pick"]["ev"] > 0.40, d
    print(json.dumps({"MARKET_EDGE_SELF_TEST": "PASS", "version": VERSION, "pick": d["upset_pick"]}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    result = [enrich(RACING, RACING_HISTORY), enrich(SPORTS, SPORTS_HISTORY)]
    print(json.dumps({"MARKET_EDGE_ENGINE": "PASS", "version": VERSION, "results": result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
