#!/usr/bin/env python3
"""Advance the six cloud PAPER accounts only from a freshly observed capture event.

This runs AFTER refreshing main and merging the genuine replay snapshot.
It never sends orders, invents missing intervals, or replays an old signal.
"""
import argparse
import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path

import category_top6_policy

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "trader-discovery/category-paper.json"

spec = importlib.util.spec_from_file_location(
    "btc_capture_paper_category", ROOT / "trader-discovery/category_paper.py"
)
category = importlib.util.module_from_spec(spec)
spec.loader.exec_module(category)
category.SWING_CAPITAL_KRW = 1_000_000
category.SWING_CAPITAL_EPOCH = 'ORIGINAL_1M_10X_V3'


def timestamp(value):
    try:
        result = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            return 0
        return result.timestamp()
    except (ValueError, TypeError):
        return 0


def apply_event(state, event):
    """Return (state, applied) without mutating the caller's state."""
    if state and (state.get("paper_only") is not True or state.get("real_trading_enabled") is not False):
        raise ValueError("LEDGER_MUST_BE_PAPER_ONLY")
    if state and (state.get("account_count") != 6 or len(state.get("accounts") or {}) != 6):
        raise ValueError("INVALID_SIX_ACCOUNT_LEDGER")
    if event.get("realtime_wallet_observations_only") is not True:
        raise ValueError("UNVERIFIED_CAPTURE_EVENT")
    at = str(event.get("at") or "")
    if not at or event.get("id") != at or timestamp(at) <= 0:
        raise ValueError("INVALID_CAPTURE_TIME")
    if timestamp(at) > dt.datetime.now(dt.timezone.utc).timestamp() + 60:
        raise ValueError("FUTURE_CAPTURE_EVENT")
    price = float(event.get("btc_mid_usd") or 0)
    if not 1000 < price < 1000000:
        raise ValueError("INVALID_CAPTURE_PRICE")
    rows = event.get("cohort_wallets")
    wallets = event.get("wallets")
    if not isinstance(rows, list) or not isinstance(wallets, dict):
        raise ValueError("INVALID_CAPTURE_WALLETS")
    if any(not isinstance(a, str) or v not in ("LONG", "SHORT", "FLAT") for a, v in wallets.items()):
        raise ValueError("INVALID_CAPTURE_SIGNAL")
    if any(not isinstance(row, dict) or row.get("address") not in wallets or
           not isinstance(row.get("category_flags"), dict) for row in rows):
        raise ValueError("UNOBSERVED_COHORT_WALLET")
    old_time = max(timestamp(state.get("updated_at")), timestamp(state.get("observed_source_at"))) if state else 0
    if timestamp(at) <= old_time:
        return state, False
    cohort = {"paper_only": True, "real_trading_enabled": False, "wallets": copy.deepcopy(rows)}
    feed = {"paper_only": True, "real_trading_enabled": False, "generated_at": at,
            "btc_mid_usd": price, "wallets": copy.deepcopy(wallets),
            "observed_wallet_count": len(wallets), "errors": []}
    ranked = category_top6_policy.apply_top6_policy(cohort)
    result = category_top6_policy.rotate_out_non_top6(copy.deepcopy(state), ranked, feed, at, category)
    result = category.advance(result, ranked, feed, at)
    result["selection_policy"] = ranked.get("selection_policy")
    result["selection_rankings"] = ranked.get("selection_rankings")
    result["observed_source_at"] = at
    result["cloud_update_source"] = "VERIFIED_GITHUB_CAPTURE"
    assert result["account_count"] == 6 and all(
        account["starting_equity_krw"] == 1000000 and account["leverage"] == 10
        for account in result["accounts"].values()
    )
    return result, True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-log", required=True)
    parser.add_argument("--snapshot-positions", required=True)
    options = parser.parse_args()

    log = json.loads(Path(options.snapshot_log).read_text(encoding="utf-8"))
    position = json.loads(Path(options.snapshot_positions).read_text(encoding="utf-8"))
    if log.get("paper_only") is not True or log.get("real_trading_enabled") is not False:
        raise ValueError("UNSAFE_SNAPSHOT_LOG")
    if position.get("paper_only") is not True or position.get("real_trading_enabled") is not False:
        raise ValueError("UNSAFE_SNAPSHOT_POSITIONS")
    if position.get("errors") or position.get("observed_wallet_count") != position.get("catalog_wallet_count"):
        raise ValueError("INCOMPLETE_SNAPSHOT")
    source_id = position.get("generated_at")
    matching = [e for e in log.get("events", []) if e.get("id") == source_id]
    if len(matching) != 1:
        raise ValueError("CAPTURE_SOURCE_EVENT_MISSING")
    event = matching[0]
    if event.get("realtime_wallet_observations_only") is not True:
        raise ValueError("CAPTURE_EVENT_NOT_VERIFIED")
    state = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    updated, applied = apply_event(state, event)
    if applied:
        LEDGER.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CLOUD_CAPTURE_PAPER_" + ("APPLIED" if applied else "ALREADY_APPLIED_OR_STALE"),
          "source=" + str(source_id), "accounts=6", "paper_only=true")


if __name__ == "__main__":
    main()
