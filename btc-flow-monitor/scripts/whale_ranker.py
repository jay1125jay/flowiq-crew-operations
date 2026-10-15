#!/usr/bin/env python3
"""BTC whale screening with forward-only observations. PAPER ONLY; never places orders."""
import datetime as dt
import hashlib
import json
import pathlib
import re
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
API = "https://api.hyperliquid.xyz/info"
ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")
MAX_WALLETS = 8
MIN_VERIFIED_CLOSES = 20
MIN_VERIFIED_DAYS = 7
FEE_BPS = 5.0
SLIPPAGE_BPS = 3.0
RECENT_KEYS_MAX = 500


def query(payload):
    req = urllib.request.Request(API, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", "User-Agent":"BTC-Flow-Paper-Research/1.1"}, method="POST")
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def fill_key(f):
    raw = "|".join(str(f.get(k, "")) for k in ("time", "hash", "tid", "px", "sz", "side", "dir", "closedPnl"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def blank_obs(now):
    return {"baseline_at": now.isoformat(), "last_observed_at": now.isoformat(), "recent_keys": [], "new_fills": 0,
            "close_count": 0, "win_count": 0, "realized_pnl": 0.0, "fees": 0.0, "notional": 0.0,
            "running_net": 0.0, "peak_net": 0.0, "max_drawdown": 0.0}


def update_forward(obs, fills, now):
    seen = set(obs.get("recent_keys", []))
    fresh = [f for f in sorted(fills, key=lambda x: int(x.get("time", 0))) if fill_key(f) not in seen]
    # The first run is a baseline only: do not pretend already-returned history was observed live.
    if not obs.get("initialized"):
        obs["recent_keys"] = [fill_key(f) for f in fills[-RECENT_KEYS_MAX:]]
        obs["initialized"] = True
        obs["last_observed_at"] = now.isoformat()
        return obs, 0
    for f in fresh:
        pnl = float(f.get("closedPnl") or 0)
        fee = float(f.get("fee") or 0)
        px = float(f.get("px") or 0)
        sz = abs(float(f.get("sz") or 0))
        notional = px * sz
        is_close = abs(pnl) > 1e-10 or "Close" in str(f.get("dir", ""))
        obs["new_fills"] = int(obs.get("new_fills", 0)) + 1
        obs["fees"] = float(obs.get("fees", 0)) + fee
        obs["notional"] = float(obs.get("notional", 0)) + notional
        if is_close:
            obs["close_count"] = int(obs.get("close_count", 0)) + 1
            obs["win_count"] = int(obs.get("win_count", 0)) + (1 if pnl > 0 else 0)
            obs["realized_pnl"] = float(obs.get("realized_pnl", 0)) + pnl
        net_delta = pnl - fee
        obs["running_net"] = float(obs.get("running_net", 0)) + net_delta
        obs["peak_net"] = max(float(obs.get("peak_net", 0)), obs["running_net"])
        obs["max_drawdown"] = max(float(obs.get("max_drawdown", 0)), obs["peak_net"] - obs["running_net"])
    obs["recent_keys"] = list(dict.fromkeys([fill_key(f) for f in fills[-RECENT_KEYS_MAX:]] + obs.get("recent_keys", [])))[:RECENT_KEYS_MAX]
    obs["last_observed_at"] = now.isoformat()
    return obs, len(fresh)


def score_wallet(address, fills, obs, now):
    btc = [x for x in fills if x.get("coin") == "BTC"]
    hist_closes = [x for x in btc if abs(float(x.get("closedPnl") or 0)) > 1e-10 or "Close" in str(x.get("dir", ""))]
    hist_pnl = sum(float(x.get("closedPnl") or 0) - float(x.get("fee") or 0) for x in btc)
    hist_wins = sum(1 for x in hist_closes if float(x.get("closedPnl") or 0) > 0)
    capped = len(fills) >= 2000
    baseline = dt.datetime.fromisoformat(obs["baseline_at"].replace("Z", "+00:00"))
    forward_days = max(0.0, (now - baseline).total_seconds() / 86400)
    closes = int(obs.get("close_count", 0))
    wins = int(obs.get("win_count", 0))
    forward_net = float(obs.get("realized_pnl", 0)) - float(obs.get("fees", 0))
    stress_cost = float(obs.get("notional", 0)) * SLIPPAGE_BPS / 10000
    stress_net = forward_net - stress_cost
    verified = forward_days >= MIN_VERIFIED_DAYS and closes >= MIN_VERIFIED_CLOSES and stress_net > 0
    # Candidate status only starts PAPER validation; it is NOT a claim that the whale is skilled.
    candidate = len(hist_closes) >= 20 and hist_pnl > 0 and (hist_wins / max(1, len(hist_closes))) >= 0.45
    score = 0.0
    if closes:
        score = round(100 * (0.45 * min(1, max(0, stress_net) / max(100, float(obs.get("max_drawdown", 0)) + 100)) +
                             0.35 * (wins / closes) + 0.20 * min(1, closes / 100)), 1)
    return {"address": address, "history_sample_fills": len(btc), "history_sample_closes": len(hist_closes),
            "history_sample_capped": capped, "history_sample_net_pnl_usd": round(hist_pnl, 2),
            "history_sample_win_rate_pct": round(100 * hist_wins / len(hist_closes), 1) if hist_closes else None,
            "forward_observed_days": round(forward_days, 2), "forward_closes": closes,
            "forward_win_rate_pct": round(100 * wins / closes, 1) if closes else None,
            "forward_net_pnl_usd": round(forward_net, 2), "forward_stress_net_pnl_usd": round(stress_net, 2),
            "forward_drawdown_usd": round(float(obs.get("max_drawdown", 0)), 2),
            "paper_candidate": candidate, "verified_whale": verified,
            "eligible_for_paper_observation": verified, "skill_score": score,
            "caveat": "Historical API sample may be truncated and is used only to seed PAPER candidates. Verified status requires forward observation."}


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    cfg = DATA / "whale-watchlist.json"
    addresses = json.loads(cfg.read_text(encoding="utf-8")).get("addresses", []) if cfg.exists() else []
    addresses = list(dict.fromkeys(str(x).lower() for x in addresses))
    if len(addresses) > MAX_WALLETS or any(not ADDRESS.fullmatch(x) for x in addresses):
        raise ValueError("invalid watchlist")
    now = dt.datetime.now(dt.timezone.utc)
    obs_path = DATA / "whale-observations.json"
    store = json.loads(obs_path.read_text(encoding="utf-8")) if obs_path.exists() else {"schema_version": 1, "wallets": {}}
    results, errors = [], []
    for a in addresses:
        try:
            fills = query({"type":"userFills", "user":a, "aggregateByTime":False})
            btc = [x for x in fills if x.get("coin") == "BTC"]
            obs = store["wallets"].get(a) or blank_obs(now)
            obs, _ = update_forward(obs, btc, now)
            store["wallets"][a] = obs
            results.append(score_wallet(a, fills, obs, now))
        except Exception as e:
            errors.append({"address":a, "error":type(e).__name__})
    store["updated_at"] = now.isoformat()
    obs_path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    results.sort(key=lambda x:(x["verified_whale"], x["paper_candidate"], x["skill_score"], x["history_sample_net_pnl_usd"]), reverse=True)
    out = {"schema_version":2, "updated_at":now.isoformat(), "paper_only":True, "real_trading_enabled":False,
           "verification_rule":{"min_forward_days":MIN_VERIFIED_DAYS,"min_forward_closes":MIN_VERIFIED_CLOSES,"stress_slippage_bps":SLIPPAGE_BPS},
           "ranked_wallets":results, "errors":errors, "watchlist_count":len(addresses),
           "paper_candidate_count":sum(1 for x in results if x["paper_candidate"]),
           "verified_count":sum(1 for x in results if x["verified_whale"]),
           "status":"NEEDS_WATCHLIST" if not addresses else ("PARTIAL" if errors else "OK")}
    (DATA / "whale-ranking.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Whale ranking", out["status"], "candidates", out["paper_candidate_count"], "verified", out["verified_count"])
    if errors:
        raise RuntimeError("wallet API errors")

if __name__ == "__main__":
    main()
