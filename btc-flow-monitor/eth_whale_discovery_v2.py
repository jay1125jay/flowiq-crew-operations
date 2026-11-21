"""ETH-specialist whale discovery for CASH FLOW V2.

Uses Hyperliquid's public leaderboard only to seed candidates, then ranks
wallets using ETH-only realized fills. This module never places orders.
"""
from __future__ import annotations

import json
import math
import pathlib
import time
import urllib.request
from datetime import datetime, timezone

LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
INFO_URL = "https://api.hyperliquid.xyz/info"
OUTPUT = pathlib.Path(__file__).resolve().parent / "trader-discovery" / "eth-candidates.json"
MIN_ACCOUNT_USD = 100_000.0
MAX_MONTHLY_TURNOVER = 100.0
MIN_ETH_FILLS = 20
MIN_ETH_CLOSES = 8
MAX_SEEDS = 30


def _number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def leaderboard_seeds(payload, excluded=(), limit=MAX_SEEDS):
    if not isinstance(payload, dict) or not isinstance(payload.get("leaderboardRows"), list):
        raise ValueError("Unexpected Hyperliquid leaderboard schema")
    excluded = {str(x).lower() for x in excluded}
    ranked = []
    for row in payload["leaderboardRows"]:
        address = str(row.get("ethAddress", "")).lower()
        if len(address) != 42 or not address.startswith("0x") or address in excluded:
            continue
        account_value = _number(row.get("accountValue"))
        windows = dict(row.get("windowPerformances") or [])
        month = windows.get("month") or {}
        pnl = _number(month.get("pnl"))
        volume = _number(month.get("vlm"))
        if account_value < MIN_ACCOUNT_USD or pnl <= 0 or volume <= 0:
            continue
        if volume / account_value > MAX_MONTHLY_TURNOVER:
            continue
        ranked.append({
            "address": address,
            "leaderboard_month_pnl_usd": pnl,
            "leaderboard_month_volume_usd": volume,
            "account_value_usd": account_value,
            "display_name": row.get("displayName"),
        })
    ranked.sort(key=lambda x: x["leaderboard_month_pnl_usd"], reverse=True)
    return ranked[:max(1, int(limit))]


def fetch_json(url, timeout=90):
    request = urllib.request.Request(url, headers={"User-Agent": "CASH-FLOW-PAPER/2"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def info(payload, timeout=20):
    request = urllib.request.Request(
        INFO_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "CASH-FLOW-PAPER/2"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def eth_fill_profile(address, start_ms, end_ms, info_fn=info, pause_seconds=6.1):
    """Aggregate ETH-only realized PnL from public fills over the requested window."""
    cursor = int(start_ms)
    end_ms = int(end_ms)
    rows_by_key = {}
    for _ in range(16):
        rows = info_fn({
            "type": "userFillsByTime", "user": address,
            "startTime": cursor, "endTime": end_ms, "aggregateByTime": False,
        })
        if not isinstance(rows, list):
            raise ValueError("Invalid userFillsByTime response")
        for row in rows:
            if row.get("coin") != "ETH":
                continue
            stamp = int(row["time"])
            if start_ms <= stamp <= end_ms:
                rows_by_key[(stamp, int(row["tid"]))] = row
        if len(rows) < 2000:
            break
        boundary = max(int(row["time"]) for row in rows)
        if boundary <= cursor:
            raise ValueError("ETH fill pagination stalled")
        cursor = boundary
        time.sleep(pause_seconds)
    else:
        raise ValueError("ETH fill pagination budget exhausted")

    fills = sorted(rows_by_key.values(), key=lambda x: (int(x["time"]), int(x["tid"])))
    realized = [_number(row.get("closedPnl")) for row in fills]
    closes = [
        pnl for row, pnl in zip(fills, realized)
        if "close" in str(row.get("dir", "")).lower()
    ]
    wins = sum(1 for pnl in closes if pnl > 0)
    losses = sum(1 for pnl in closes if pnl < 0)
    gross_profit = sum(pnl for pnl in closes if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in closes if pnl < 0))
    total_volume = sum(abs(_number(row.get("sz")) * _number(row.get("px"))) for row in fills)
    net_realized = sum(closes)
    return {
        "eth_fill_count": len(fills),
        "eth_close_count": len(closes),
        "eth_wins": wins,
        "eth_losses": losses,
        "eth_win_rate_pct": (wins / len(closes) * 100.0) if closes else 0.0,
        "eth_realized_pnl_usd": net_realized,
        "eth_profit_factor": (gross_profit / gross_loss) if gross_loss else (999.0 if gross_profit else 0.0),
        "eth_volume_usd": total_volume,
        "eth_sample_from_ms": int(start_ms),
        "eth_sample_to_ms": end_ms,
    }


def rank_eth_candidates(seeds, profiles, limit=5):
    eligible = []
    for seed in seeds:
        profile = profiles.get(seed["address"])
        if not profile:
            continue
        if profile["eth_fill_count"] < MIN_ETH_FILLS or profile["eth_close_count"] < MIN_ETH_CLOSES:
            continue
        if profile["eth_realized_pnl_usd"] <= 0 or profile["eth_win_rate_pct"] <= 50:
            continue
        eligible.append({**seed, **profile, "asset_specialty": "ETH", "paper_status": "CANDIDATE"})
    eligible.sort(
        key=lambda x: (
            x["eth_realized_pnl_usd"],
            x["eth_profit_factor"],
            x["eth_win_rate_pct"],
            x["leaderboard_month_pnl_usd"],
        ),
        reverse=True,
    )
    return eligible[:max(0, int(limit))]


def discover(excluded=(), seed_limit=MAX_SEEDS, candidate_limit=5, now_ms=None):
    now_ms = int(now_ms or time.time() * 1000)
    start_ms = now_ms - 30 * 24 * 60 * 60 * 1000
    payload = fetch_json(LEADERBOARD_URL)
    seeds = leaderboard_seeds(payload, excluded=excluded, limit=seed_limit)
    profiles = {}
    for index, seed in enumerate(seeds, 1):
        try:
            profiles[seed["address"]] = eth_fill_profile(seed["address"], start_ms, now_ms)
            print("ETH_SCREEN_OK", index, seed["address"][:10], flush=True)
            time.sleep(6.1)
        except Exception as exc:
            print("ETH_SCREEN_HOLD", seed["address"][:10], str(exc)[:180], flush=True)
    selected = rank_eth_candidates(seeds, profiles, candidate_limit)
    result = {
        "schema_version": 1,
        "paper_only": True,
        "real_trading_enabled": False,
        "source": "Hyperliquid public leaderboard + ETH-only user fills",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_days": 30,
        "seed_count": len(seeds),
        "profiled_count": len(profiles),
        "candidate_count": len(selected),
        "selection_rules": {
            "minimum_account_value_usd": MIN_ACCOUNT_USD,
            "maximum_monthly_turnover_multiple": MAX_MONTHLY_TURNOVER,
            "minimum_eth_fills": MIN_ETH_FILLS,
            "minimum_eth_closes": MIN_ETH_CLOSES,
            "minimum_eth_realized_pnl_usd": 0,
            "minimum_eth_win_rate_pct_exclusive": 50,
        },
        "candidates": selected,
        "not_selected": [
            {"address": seed["address"], "reason": "insufficient ETH-only sample or non-positive ETH results"}
            for seed in seeds if seed["address"] not in {x["address"] for x in selected}
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".tmp")
    temp.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(OUTPUT)
    print("ETH_CANDIDATES", len(selected), "OUTPUT", OUTPUT, flush=True)
    return result


if __name__ == "__main__":
    discover()
