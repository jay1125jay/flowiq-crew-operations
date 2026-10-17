#!/usr/bin/env python3
"""Classify every wallet in the existing ranked snapshot. PAPER research only.

No network calls or orders. Historical sample data is not sufficient to infer
holding times, actual leverage, total wallet equity or complete drawdowns.
"""
import argparse
import datetime as dt
import json
from pathlib import Path

DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "data" / "whale-ranking.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "classification-snapshot.json"
CATEGORIES = ("WHALE", "HIGH_WIN_RATE", "HIGH_PROFIT", "CONSISTENT", "SCALPER", "SWING")

def classify(wallet):
    closes = int(wallet.get("history_sample_closes") or 0)
    span = float(wallet.get("history_span_days") or 0)
    capped = bool(wallet.get("history_sample_capped"))
    win = wallet.get("history_sample_win_rate_pct")
    profit = float(wallet.get("history_sample_net_pnl_usd") or 0)
    pf = float(wallet.get("history_profit_factor") or 0)
    concentration = float(wallet.get("history_largest_win_share_pct") or 100)
    notional = float(wallet.get("history_avg_fill_notional_usd") or 0)
    drawdown = wallet.get("forward_drawdown_usd")
    fwd_days = float(wallet.get("forward_observed_days") or 0)
    fwd_closes = int(wallet.get("forward_closes") or 0)
    categories = {}
    # These are candidate research labels, NOT proven trader skill.
    categories["WHALE"] = "CANDIDATE" if notional >= 20000 and closes >= 20 else "NOT_ESTABLISHED"
    categories["HIGH_WIN_RATE"] = "CANDIDATE" if closes >= 50 and win is not None and float(win) >= 65 else "NOT_ESTABLISHED"
    categories["HIGH_PROFIT"] = "CANDIDATE" if closes >= 50 and profit >= 10000 else "NOT_ESTABLISHED"
    # Relative drawdown cannot be determined without wallet equity. No stable label yet.
    categories["CONSISTENT"] = "INSUFFICIENT_DATA"
    # A high fill frequency does not prove a short holding period.
    categories["SCALPER"] = "NEEDS_ROUND_TRIP_HOLDING_TIMES"
    categories["SWING"] = "NEEDS_ROUND_TRIP_HOLDING_TIMES"
    return {
        "address": wallet["address"], "categories": categories,
        "history_closes": closes, "history_span_days": span,
        "history_capped": capped, "forward_days": fwd_days,
        "forward_closes": fwd_closes, "forward_drawdown_usd": drawdown,
        "verified": bool(wallet.get("verified_whale", False)),
        "validation": "UNVERIFIED" if capped or fwd_days < 7 or fwd_closes < 20 else "REQUIRES_DEEPER_VALIDATION",
        "limitations": ["history_capped"] if capped else [],
    }

def build(data):
    wallets = [classify(w) for w in data.get("ranked_wallets", []) if w.get("address")]
    counts = {k: sum(w["categories"][k] == "CANDIDATE" for w in wallets) for k in CATEGORIES}
    return {
        "schema_version": 1, "paper_only": True, "real_trading_enabled": False,
        "source_updated_at": data.get("updated_at"),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "wallet_count": len(wallets), "candidate_counts": counts,
        "important_note": "Labels are exploratory and overlapping; no demonstrated followable edge.",
        "wallets": wallets,
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = p.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    result = build(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"wallet_count": result["wallet_count"], "candidate_counts": result["candidate_counts"]}, ensure_ascii=False))

if __name__ == "__main__":
    main()
