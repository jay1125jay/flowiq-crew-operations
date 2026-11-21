"""Dual-asset Hyperliquid PAPER reconciler. No order-placement endpoints."""
from __future__ import annotations
import copy
import datetime as dt
import json
import math
import os
import pathlib
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

from cash_flow_v2_core import (
    ASSETS, INITIAL_KRW, LEVERAGE, FEE_RATE, SLIPPAGE_RATE,
    new_ledger, apply_wallet_fill, mark_account, close_position_fraction, totals, migrate_btc_ledger,
)

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "trader-discovery"
LEGACY_PATH = DATA / "wallet-paper.json"
OUT = DATA / "wallet-paper-v2.json"
SELECTED = DATA / "selected-whales.json"
API = "https://api.hyperliquid.xyz/info"
MAX_QUOTE_AGE_SECONDS = 15
MAX_FOLLOW_GAP = 0.003
REQUEST_BUDGET_PER_SECOND = 10.0
_lock = threading.Lock()
_next_request = 0.0
_limited_until = 0.0


def info(payload):
    global _next_request, _limited_until
    with _lock:
        now = time.monotonic()
        if now < _limited_until:
            raise urllib.error.HTTPError(API, 429, "shared API cooldown", None, None)
        wait = max(0.0, _next_request - now)
        if wait:
            time.sleep(wait)
        weight = 120 if payload.get("type") == "userFillsByTime" else 2
        _next_request = time.monotonic() + weight / REQUEST_BUDGET_PER_SECOND
    req = urllib.request.Request(API, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "CASH-FLOW-PAPER/2"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            with _lock:
                _limited_until = time.monotonic() + 120
        raise


def finite(value, label):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("non-finite " + label)
    return value


def fetch_fills(wallet, coin, start_ms, end_ms):
    rows_by_key = {}
    cursor = max(0, int(start_ms))
    for _ in range(16):
        rows = info({"type": "userFillsByTime", "user": wallet,
                     "startTime": cursor, "endTime": int(end_ms),
                     "aggregateByTime": False})
        if not isinstance(rows, list):
            raise ValueError("invalid fill response")
        for row in rows:
            if row.get("coin") == coin:
                ms = int(row["time"])
                if start_ms <= ms <= end_ms:
                    rows_by_key[(ms, int(row["tid"]))] = row
        if len(rows) < 2000:
            return sorted(rows_by_key.values(), key=lambda r: (int(r["time"]), int(r["tid"])))
        boundary = max(int(r["time"]) for r in rows)
        if boundary <= cursor:
            raise ValueError("fill pagination stalled")
        cursor = boundary
    raise ValueError("fill pagination budget exhausted")


def follow_snapshot(account, coin, size, entry, bid, ask, stamp):
    if not size or account.get("position"):
        return "not_needed"
    side = 1 if size > 0 else -1
    execution = (ask if side > 0 else bid) * (1 + side * SLIPPAGE_RATE)
    gap = abs(execution - entry) / entry
    if gap > MAX_FOLLOW_GAP:
        account["follow_wait_gap_pct"] = gap * 100
        return "gap_wait"
    notional = account["equity_krw"] * LEVERAGE
    fee = notional * FEE_RATE
    account["cash_krw"] -= fee
    account["fees_krw"] += fee
    account["position"] = {
        "side": side, "entry_price": execution, "notional_krw": notional,
        "entry_fee_krw": fee, "opened_at": stamp, "reason": "snapshot_follow",
        "source_entry": entry, "entry_gap_pct": gap * 100,
    }
    account["source_size"] = size
    account["initialized"] = True
    mark_account(account, (bid + ask) / 2, stamp)
    return "followed"


def apply_ordered_coin(ledger, wallet, coin, rows, source_equity, snapshot_ms):
    account = ledger["wallets"][wallet][coin]
    if not account.get("initialized"):
        return "baseline_required"
    pending = []
    seen = {tuple(k) for k in account.get("stream_keys", [])}
    for row in rows:
        key = (int(row["time"]), int(row["tid"]))
        if key not in seen and int(account.get("fill_cursor", 0)) <= key[0] <= snapshot_ms:
            pending.append(row)
    pending.sort(key=lambda r: (int(r["time"]), int(r["tid"])))
    remaining = pending[:]
    while remaining:
        expected = account["source_size"]
        index = next((i for i, row in enumerate(remaining)
            if math.isclose(finite(row["startPosition"], "startPosition"), expected,
                            rel_tol=0, abs_tol=1e-8)), None)
        if index is None:
            raise ValueError(coin + " source fill chain mismatch")
        row = remaining.pop(index)
        fill_ms = int(row["time"])
        now_ms = int(time.time() * 1000)
        allow_open = -2000 <= now_ms - fill_ms <= 15000
        apply_wallet_fill(ledger, wallet, row, source_equity, allow_open=allow_open)
    return "fills_applied" if pending else "no_new_fills"


def reconcile_wallet(ledger, wallet):
    state = info({"type": "clearinghouseState", "user": wallet})
    equity = finite(state["marginSummary"]["accountValue"], "source equity")
    snapshot_ms = int(state["time"])
    positions = {
        item["position"]["coin"]: item["position"]
        for item in state.get("assetPositions", [])
        if item.get("position", {}).get("coin") in ASSETS
    }
    results = {}
    for coin in ASSETS:
        account = ledger["wallets"][wallet][coin]
        source = positions.get(coin, {})
        source_size = finite(source.get("szi", 0), coin + " source size")
        source_entry = finite(source["entryPx"], coin + " source entry") if source_size else None
        book = info({"type": "l2Book", "coin": coin})
        if book.get("coin") != coin or len(book.get("levels", [])) < 2:
            raise ValueError(coin + " invalid order book")
        bid = finite(book["levels"][0][0]["px"], coin + " bid")
        ask = finite(book["levels"][1][0]["px"], coin + " ask")
        quote_ms = int(book["time"])
        now_ms = int(time.time() * 1000)
        if not (0 < bid <= ask) or now_ms - quote_ms > MAX_QUOTE_AGE_SECONDS * 1000 or quote_ms - now_ms > 2000:
            raise ValueError(coin + " stale or invalid quote")
        stamp = dt.datetime.fromtimestamp(quote_ms / 1000, dt.timezone.utc).isoformat()

        if not account.get("initialized"):
            account["source_size"] = source_size
            account["fill_cursor"] = snapshot_ms
            account["initialized"] = True
            follow = follow_snapshot(account, coin, source_size, source_entry, bid, ask, stamp)
            results[coin] = "baseline_" + follow
        else:
            cursor = int(account.get("fill_cursor", 0))
            if snapshot_ms < cursor:
                raise ValueError(coin + " old source snapshot")
            # Re-fetch a short overlap so same-millisecond fills omitted by a prior
            # WebSocket disconnect can still be recovered by (time, tid) deduplication.
            rows = fetch_fills(wallet, coin, max(0, cursor - 1000), snapshot_ms) if snapshot_ms >= cursor else []
            before_replay = copy.deepcopy(account)
            try:
                result = apply_ordered_coin(ledger, wallet, coin, rows, equity, snapshot_ms)
                if not math.isclose(account["source_size"], source_size, rel_tol=0, abs_tol=1e-8):
                    raise ValueError(coin + " fill history gap; account held for recovery")
            except ValueError as gap_error:
                is_history_gap = (
                    "source fill chain mismatch" in str(gap_error) or
                    "fill history gap" in str(gap_error)
                )
                if not is_history_gap or snapshot_ms - cursor < 300_000:
                    raise
                # Discard a partial replay and reconcile only the verified position-size
                # reduction. Never guess missing entry prices or invent extra exposure.
                ledger["wallets"][wallet][coin] = before_replay
                account = ledger["wallets"][wallet][coin]
                prior_size = finite(account.get("source_size", 0.0), coin + " prior source size")
                position = account.get("position")
                if position:
                    if not prior_size or prior_size * position["side"] <= 0:
                        raise ValueError(coin + " follower/source direction mismatch during gap recovery")
                    retained = 0.0 if prior_size * source_size <= 0 else min(1.0, abs(source_size / prior_size))
                    if retained < 1.0:
                        exit_quote = bid if position["side"] > 0 else ask
                        close_position_fraction(account, 1.0 - retained, exit_quote, stamp,
                                                "snapshot_gap_recovery")
                account["history_gap_at"] = stamp
                account["history_gap_reason"] = "Missing source fills; reconciled at verified source position size"
                account["history_gap_start_ms"] = cursor
                account["source_size"] = source_size
                result = "snapshot_gap_recovered"
            account["fill_cursor"] = snapshot_ms
            if not account.get("position") and source_size:
                result += "+" + follow_snapshot(account, coin, source_size, source_entry, bid, ask, stamp)
            results[coin] = result
        mark_account(account, (bid + ask) / 2, stamp)
        account["source_size"] = source_size
        account["source_entry_px"] = source_entry
        account["source_equity_usd"] = equity
        account["source_snapshot_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        account["source_quote_at"] = stamp
        account["error"] = None
    return results


def latest_main_text(relative_path):
    repo_root = ROOT.parent
    if not (repo_root / ".git").exists():
        local_path = repo_root / relative_path
        return local_path.read_text(encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "fetch", "--depth=1", "origin", "main"],
                   check=True, capture_output=True, text=True, timeout=120)
    result = subprocess.run(["git", "-C", str(repo_root), "show", "origin/main:" + relative_path],
                            check=True, capture_output=True, text=True, timeout=60)
    return result.stdout


def load_ledger(addresses):
    if OUT.exists():
        ledger = json.loads(OUT.read_text(encoding="utf-8"))
        if ledger.get("paper_only") is not True or ledger.get("real_trading_enabled") is not False:
            raise ValueError("Refusing non-PAPER V2 ledger")
        if set(ledger.get("wallets", {})) != set(addresses):
            raise ValueError("Selected whale set changed; explicit migration required")
        return ledger
    raw = latest_main_text("btc-flow-monitor/trader-discovery/wallet-paper.json").strip()
    if not raw:
        raise ValueError("Latest main BTC ledger is empty; refusing to create replacement accounts")
    old = json.loads(raw)
    ledger = migrate_btc_ledger(old)
    if set(ledger["wallets"]) == set(addresses):
        return ledger
    raise ValueError("Legacy whale set differs from current selection; preserve and review before migration")


def save_atomic(ledger):
    ledger["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    ledger["totals"] = totals(ledger)
    DATA.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="wallet-paper-v2-", suffix=".tmp", dir=DATA)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(ledger, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, OUT)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    selected = json.loads(latest_main_text("btc-flow-monitor/trader-discovery/selected-whales.json"))
    addresses = [row["address"].lower() for row in selected]
    if len(addresses) != 5 or len(set(addresses)) != 5:
        raise ValueError("Expected five distinct selected whales")
    ledger = load_ledger(addresses)
    ledger["selected_whales"] = selected
    ledger["paper_only"] = True
    ledger["real_trading_enabled"] = False
    ok = 0
    for wallet in addresses:
        candidate = copy.deepcopy(ledger)
        try:
            result = reconcile_wallet(candidate, wallet)
            candidate["wallets"][wallet]["last_reconcile"] = result
            ledger["wallets"][wallet] = candidate["wallets"][wallet]
            ok += 1
            print("V2_RECONCILE_OK", wallet[:10], result, flush=True)
        except (OSError, ValueError, KeyError, IndexError, TypeError, urllib.error.HTTPError) as exc:
            for coin in ASSETS:
                ledger["wallets"][wallet][coin]["error"] = str(exc)[:240]
            print("V2_RECONCILE_HOLD", wallet[:10], str(exc)[:240], flush=True)
        save_atomic(ledger)
    ledger["observed_count"] = ok
    save_atomic(ledger)
    print("V2_SUMMARY", json.dumps(ledger["totals"], ensure_ascii=False), flush=True)
    if not ok:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
