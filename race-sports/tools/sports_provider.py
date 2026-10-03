#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, time, urllib.request, urllib.error
from datetime import datetime, date, timezone, timedelta
from typing import Any

KST = timezone(timedelta(hours=9))
BASES = [
    "https://www.sofascore.com/api/v1",
    "https://api.sofascore.com/api/v1",
]
SPORTS = {
    "SOCCER": {
        "slug": "football",
        "aliases": [
            ("england", "premier league"),
            ("spain", "laliga"),
            ("germany", "bundesliga"),
            ("italy", "serie a"),
            ("france", "ligue 1"),
            ("south korea", "k league 1"),
            ("europe", "uefa champions league"),
            ("europe", "uefa europa league"),
        ],
    },
    "BASEBALL": {
        "slug": "baseball",
        "aliases": [
            ("usa", "mlb"),
            ("south korea", "kbo"),
            ("japan", "npb"),
            ("japan", "pro yakyu"),
        ],
    },
    "BASKETBALL": {
        "slug": "basketball",
        "aliases": [
            ("usa", "nba"),
            ("south korea", "kbl"),
            ("europe", "euroleague"),
        ],
    },
    "VOLLEYBALL": {
        "slug": "volleyball",
        "aliases": [
            ("south korea", "v-league"),
            ("south korea", "v league"),
            ("italy", "superlega"),
            ("poland", "plusliga"),
            ("turkey", "sultanlar ligi"),
        ],
    },
}
DENY = (
    "u17","u18","u19","u20","u21","u22","u23","youth","reserve","reserves",
    "women 2","women's 2","2nd","second division","division 2","league 2",
    "serie b","bundesliga 2","2. bundesliga","k league 2","g league",
)
STATUS_MAP = {
    "notstarted": "SCHEDULED",
    "inprogress": "LIVE",
    "finished": "FINAL",
    "postponed": "POSTPONED",
    "canceled": "CANCELLED",
    "cancelled": "CANCELLED",
    "interrupted": "SUSPENDED",
}

def _norm(s: Any) -> str:
    return " ".join(str(s or "").strip().lower().replace("_"," ").split())

def _http_json(url: str, timeout: int = 18, retries: int = 2) -> dict:
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; RACEIQ/1.0; +https://github.com/jay1125jay/flowiq-crew-operations)",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status != 200:
                    raise RuntimeError(f"HTTP_{r.status}")
                raw = r.read()
            obj = json.loads(raw.decode("utf-8"))
            if not isinstance(obj, dict):
                raise RuntimeError("JSON_NOT_OBJECT")
            return obj
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(1.0 + attempt)
    raise RuntimeError(f"FETCH_FAILED:{url}:{last!r}")

def fetch_scheduled_raw(sport: str, day: str) -> tuple[list[dict], str]:
    cfg = SPORTS[sport]
    errors = []
    for base in BASES:
        url = f"{base}/sport/{cfg['slug']}/scheduled-events/{day}"
        try:
            obj = _http_json(url)
            events = obj.get("events")
            if not isinstance(events, list):
                raise RuntimeError("EVENTS_NOT_LIST")
            return events, url
        except Exception as e:
            errors.append(str(e))
    raise RuntimeError(" | ".join(errors))

def _tournament_parts(ev: dict) -> tuple[str,str]:
    t = ev.get("tournament") or {}
    ut = t.get("uniqueTournament") or {}
    name = ut.get("name") or t.get("name") or ""
    cat = (ut.get("category") or t.get("category") or {})
    country = cat.get("name") or ""
    return str(country), str(name)

def is_top_tier(sport: str, ev: dict) -> tuple[bool,str]:
    country, tour = _tournament_parts(ev)
    nc, nt = _norm(country), _norm(tour)
    joined = f"{nc} {nt}"
    if any(x in joined for x in DENY):
        return False, "DENY_LOWER_YOUTH_RESERVE"
    for ac, at in SPORTS[sport]["aliases"]:
        if _norm(ac) in nc and _norm(at) in nt:
            return True, "ALLOW_TOP_TIER"
    return False, "NOT_ALLOWLISTED_TOP_TIER"

def _team_name(ev: dict, key: str) -> str:
    t = ev.get(key) or {}
    return str(t.get("name") or t.get("shortName") or t.get("slug") or key.upper())

def _score(ev: dict, key: str):
    s = ev.get(key) or {}
    for k in ("current","display","normaltime","period1"):
        v = s.get(k)
        if isinstance(v, (int,float)):
            return v
    return None

def _winner_key(sport: str, hs, aas):
    if hs is None or aas is None:
        return None
    if hs > aas: return "HOME"
    if aas > hs: return "AWAY"
    if sport == "SOCCER": return "DRAW"
    return None

def parse_event(sport: str, ev: dict, requested_day: str) -> dict | None:
    ts = ev.get("startTimestamp")
    if not isinstance(ts, (int,float)):
        return None
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(KST)
    if dt.date().isoformat() != requested_day:
        return None
    ok, reason = is_top_tier(sport, ev)
    if not ok:
        return None
    status_raw = _norm((ev.get("status") or {}).get("type"))
    status = STATUS_MAP.get(status_raw, "SCHEDULED")
    home = _team_name(ev, "homeTeam")
    away = _team_name(ev, "awayTeam")
    hs = _score(ev, "homeScore")
    aas = _score(ev, "awayScore")
    country, tournament = _tournament_parts(ev)
    eid = ev.get("id")
    if eid is None:
        return None
    outcomes = [
        {"key":"HOME","name":home},
        {"key":"AWAY","name":away},
    ]
    if sport == "SOCCER":
        outcomes.insert(1, {"key":"DRAW","name":"무승부"})
    out = {
        "id": f"SPORTS-{sport}-{eid}",
        "provider_event_id": str(eid),
        "domain": "SPORTS",
        "sport": sport,
        "provider": "SOFASCORE_PUBLIC",
        "provider_kind": "PUBLIC_SCORE_FEED",
        "competition": tournament,
        "country": country,
        "event_date": requested_day,
        "start_time": dt.strftime("%H:%M"),
        "start_timestamp": int(ts),
        "status": status,
        "title": f"{home} vs {away}",
        "home": home,
        "away": away,
        "market_type": "THREE_WAY" if sport == "SOCCER" else "TWO_WAY",
        "outcomes": outcomes,
        "tier": "TOP",
        "tier_filter": reason,
        "data_state": "FRESH",
        "source_url": f"https://www.sofascore.com/event/{eid}",
    }
    if status == "FINAL" and hs is not None and aas is not None:
        wk = _winner_key(sport, hs, aas)
        out["result"] = {
            "official": False,
            "status": "CONFIRMED",
            "home_score": hs,
            "away_score": aas,
            "winner_key": wk,
            "source": "SOFASCORE_PUBLIC",
            "updated_at": datetime.now(KST).isoformat(),
        }
    elif hs is not None and aas is not None:
        out["score"] = {"home": hs, "away": aas}
    return out

def fetch_sport_day(sport: str, day: str) -> tuple[list[dict],dict]:
    raw, url = fetch_scheduled_raw(sport, day)
    kept = []
    for ev in raw:
        try:
            x = parse_event(sport, ev, day)
            if x: kept.append(x)
        except Exception:
            continue
    kept.sort(key=lambda e:(e.get("start_timestamp",0), e["id"]))
    meta = {
        "sport": sport,
        "status": "PASS",
        "raw_events": len(raw),
        "top_tier_events": len(kept),
        "source_url": url,
    }
    return kept, meta

def _fixture_event(sport: str) -> dict:
    tour = {
        "SOCCER": ("England","Premier League"),
        "BASEBALL": ("USA","MLB"),
        "BASKETBALL": ("USA","NBA"),
        "VOLLEYBALL": ("South Korea","V-League"),
    }[sport]
    ts = int(datetime(2026,10,4,12,0,tzinfo=KST).timestamp())
    return {
        "id": 123,
        "startTimestamp": ts,
        "status": {"type":"finished"},
        "tournament": {"uniqueTournament":{"name":tour[1],"category":{"name":tour[0]}}},
        "homeTeam":{"name":"Home"},
        "awayTeam":{"name":"Away"},
        "homeScore":{"current":2},
        "awayScore":{"current":1},
    }

def self_test():
    for sport in SPORTS:
        ev = _fixture_event(sport)
        x = parse_event(sport, ev, "2026-10-04")
        assert x and x["sport"] == sport
        assert x["tier"] == "TOP"
        assert x["status"] == "FINAL"
        assert x["result"]["winner_key"] == "HOME"
        low = json.loads(json.dumps(ev))
        low["tournament"]["uniqueTournament"]["name"] = "K League 2"
        assert parse_event(sport, low, "2026-10-04") is None
    print(json.dumps({"SPORTS_PROVIDER_SELF_TEST":"PASS","sports":list(SPORTS)},ensure_ascii=False))

def live_probe(day: str | None = None):
    day = day or datetime.now(KST).date().isoformat()
    rows = {}
    for sport in SPORTS:
        events, meta = fetch_sport_day(sport, day)
        rows[sport] = meta
    print(json.dumps({"SPORTS_PROVIDER_LIVE_PROBE":"PASS","date":day,"providers":rows},ensure_ascii=False))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--live-probe", action="store_true")
    ap.add_argument("--date")
    args = ap.parse_args()
    if args.self_test: return self_test()
    if args.live_probe: return live_probe(args.date)
    live_probe(args.date)

if __name__ == "__main__":
    main()
