"""CASH FLOW V2 isolated PAPER accounting core for BTC and ETH."""
from __future__ import annotations
import copy
import math
from datetime import datetime, timezone

ASSETS = ("BTC", "ETH")
INITIAL_KRW = 1_000_000
LEVERAGE = 10
FEE_RATE = 0.0005
SLIPPAGE_RATE = 0.0003
MAX_FOLLOW_GAP = 0.003


def _finite(value, name):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Invalid {name}")
    return value


def new_account(capital=INITIAL_KRW):
    capital = _finite(capital, "capital")
    if capital <= 0:
        raise ValueError("Capital must be positive")
    return {
        "initial_krw": capital, "cash_krw": capital, "equity_krw": capital,
        "position": None, "closed": [], "fill_count": 0,
        "fees_krw": 0.0, "fees_history_complete": True,
        "fill_cursor": 0, "stream_keys": [],
        "source_size": 0.0, "peak_equity_krw": capital,
        "max_drawdown_pct": 0.0, "last_price": None, "updated_at": None,
    }


def new_ledger(wallets, capital=INITIAL_KRW):
    addresses = [str(w).lower() for w in wallets]
    if len(set(addresses)) != len(addresses):
        raise ValueError("Duplicate wallet")
    return {
        "schema_version": 2, "paper_only": True, "real_trading_enabled": False,
        "initial_krw_per_wallet_asset": capital, "leverage": LEVERAGE,
        "fee_rate": FEE_RATE, "slippage_rate": SLIPPAGE_RATE,
        "wallets": {
            wallet: {asset: new_account(capital) for asset in ASSETS}
            for wallet in addresses
        },
        "updated_at": None,
    }


def _mark(account, price, stamp):
    position = account["position"]
    unrealized = 0.0
    if position:
        direction = position["side"]
        unrealized = direction * (price / position["entry_price"] - 1.0) * position["notional_krw"]
        maintenance = 0.005 * position["notional_krw"] * price / position["entry_price"]
        if account["cash_krw"] + unrealized <= maintenance:
            _close(account, 1.0, price, stamp, "liquidation")
            unrealized = 0.0
    account["equity_krw"] = max(0.0, account["cash_krw"] + unrealized)
    account["last_price"] = price
    account["updated_at"] = stamp
    peak = max(account["peak_equity_krw"], account["equity_krw"])
    account["peak_equity_krw"] = peak
    if peak > 0:
        account["max_drawdown_pct"] = max(
            account["max_drawdown_pct"], 100.0 * (1.0 - account["equity_krw"] / peak)
        )


def mark_account(account, price, stamp=None):
    price = _finite(price, "mark price")
    if price <= 0:
        raise ValueError("Mark price must be positive")
    _mark(account, price, stamp or datetime.now(timezone.utc).isoformat())
    return account


def _close(account, fraction, market_price, stamp, reason):
    pos = account["position"]
    fraction = min(1.0, max(0.0, fraction))
    if not pos or fraction <= 0:
        return
    sign = pos["side"]
    quantity_notional = pos["notional_krw"] * fraction
    entry_fee = pos["entry_fee_krw"] * fraction
    exit_price = market_price * (1.0 - sign * SLIPPAGE_RATE)
    gross = sign * quantity_notional * (exit_price / pos["entry_price"] - 1.0)
    exit_fee = quantity_notional * (exit_price / pos["entry_price"]) * FEE_RATE
    net = gross - entry_fee - exit_fee
    account["cash_krw"] = max(0.0, account["cash_krw"] + gross - exit_fee)
    account["fees_krw"] += exit_fee
    account["closed"].append({
        "opened_at": pos["opened_at"], "closed_at": stamp,
        "side": "LONG" if sign > 0 else "SHORT",
        "entry_price": pos["entry_price"], "exit_price": exit_price,
        "gross_pnl_krw": gross, "entry_fee_krw": entry_fee,
        "exit_fee_krw": exit_fee, "net_pnl_krw": net, "reason": reason,
    })
    if fraction >= 1.0 - 1e-12:
        account["position"] = None
    else:
        pos["notional_krw"] -= quantity_notional
        pos["entry_fee_krw"] -= entry_fee


def apply_fill(account, row, source_equity_usd, allow_open=True, stamp=None):
    """Apply one source fill. The caller must sequence fills per wallet+coin."""
    coin = row.get("coin")
    if coin not in ASSETS:
        raise ValueError("Only BTC and ETH are supported")
    price = _finite(row.get("px"), "fill price")
    size = _finite(row.get("sz"), "fill size")
    before = _finite(row.get("startPosition"), "source position")
    source_equity_usd = _finite(source_equity_usd, "source equity")
    if price <= 0 or size <= 0 or row.get("side") not in ("B", "A"):
        raise ValueError("Invalid fill")
    ms, tid = int(row["time"]), int(row["tid"])
    key = [ms, tid]
    if key in account["stream_keys"] or ms < account["fill_cursor"]:
        return "duplicate"
    if not math.isclose(before, account["source_size"], rel_tol=0, abs_tol=1e-8):
        raise ValueError("Source position chain mismatch")
    sign = 1 if row["side"] == "B" else -1
    stamp = stamp or datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()
    _mark(account, price, stamp)
    reduction = min(size, abs(before)) if before * sign < 0 else 0.0
    pos = account["position"]
    if reduction and pos and pos["side"] == -sign:
        _close(account, reduction / abs(before), price, stamp, "source_fill")
    opening = size - reduction
    pos = account["position"]
    if allow_open and opening > 1e-12:
        if pos and pos["side"] != sign:
            raise ValueError("Follower/source direction mismatch")
        used = pos["notional_krw"] if pos else 0.0
        budget = account["equity_krw"]
        if pos:
            if source_equity_usd <= 0:
                raise ValueError("Missing source equity for scale-in")
            target = min(max(0.0, budget * LEVERAGE - used),
                         opening * price / source_equity_usd * budget)
        else:
            target = budget * LEVERAGE
        if target > 0:
            entry = price * (1.0 + sign * SLIPPAGE_RATE)
            fee = target * FEE_RATE
            account["cash_krw"] -= fee
            account["fees_krw"] += fee
            if pos:
                old_qty = pos["notional_krw"] / pos["entry_price"]
                new_qty = target / entry
                pos["notional_krw"] += target
                pos["entry_price"] = pos["notional_krw"] / (old_qty + new_qty)
                pos["entry_fee_krw"] += fee
            else:
                account["position"] = {
                    "side": sign, "entry_price": entry, "notional_krw": target,
                    "entry_fee_krw": fee, "opened_at": stamp,
                }
    account["source_size"] = before + sign * size
    account["fill_cursor"] = ms
    account["stream_keys"] = [k for k in account["stream_keys"] if k[0] == ms] + [key]
    account["fill_count"] += 1
    account["last_fill"] = {"time": ms, "tid": tid, "price": price, "coin": coin}
    _mark(account, price, stamp)
    return "applied"


def apply_wallet_fill(ledger, wallet, row, source_equity_usd, allow_open=True):
    if ledger.get("paper_only") is not True or ledger.get("real_trading_enabled") is not False:
        raise ValueError("PAPER_ONLY invariant violated")
    coin = row.get("coin")
    wallet = wallet.lower()
    if coin not in ASSETS or wallet not in ledger["wallets"]:
        return "ignored"
    account = ledger["wallets"][wallet][coin]
    return apply_fill(account, row, source_equity_usd, allow_open)


def totals(ledger):
    if ledger.get("paper_only") is not True or ledger.get("real_trading_enabled") is not False:
        raise ValueError("PAPER_ONLY invariant violated")
    by_asset = {}
    total_initial = total_equity = total_fees = 0.0
    for coin in ASSETS:
        accounts = [wallet[coin] for wallet in ledger["wallets"].values()]
        initial = sum(a["initial_krw"] for a in accounts)
        equity = sum(a["equity_krw"] for a in accounts)
        fees = sum(a["fees_krw"] for a in accounts)
        by_asset[coin] = {
            "initial_krw": initial, "equity_krw": equity,
            "net_pnl_krw": equity - initial,
            "return_pct": (equity / initial - 1.0) * 100 if initial else 0.0,
            "fees_krw": fees, "fees_history_complete": all(
                a.get("fees_history_complete", True) for a in accounts
            ), "accounts": len(accounts),
        }
        total_initial += initial
        total_equity += equity
        total_fees += fees
    return {
        "by_asset": by_asset, "initial_krw": total_initial,
        "equity_krw": total_equity, "net_pnl_krw": total_equity-total_initial,
        "return_pct": (total_equity/total_initial-1.0)*100 if total_initial else 0.0,
        "fees_krw": total_fees,
        "fees_history_complete": all(
            account.get("fees_history_complete", True)
            for wallet in ledger["wallets"].values() for account in wallet.values()
        ),
        "paper_only": True, "real_trading_enabled": False,
    }


def _migrate_legacy_btc_account(old, capital):
    account = new_account(capital)
    account["cash_krw"] = _finite(old.get("cash", capital), "legacy cash")
    account["equity_krw"] = _finite(old.get("equity_krw", account["cash_krw"]), "legacy equity")
    account["fill_cursor"] = int(old.get("fill_cursor", 0) or 0)
    account["stream_keys"] = copy.deepcopy(old.get("stream_keys", []))
    account["source_size"] = _finite(old.get("source_size", old.get("source_btc_size", 0.0)) or 0.0,
                                     "legacy source size")
    account["fill_count"] = int(old.get("fill_count", 0) or 0)
    account["peak_equity_krw"] = _finite(old.get("peak_krw", capital), "legacy peak")
    account["max_drawdown_pct"] = _finite(old.get("max_drawdown_pct", 0.0), "legacy drawdown")
    account["last_price"] = old.get("price")
    account["updated_at"] = old.get("last_at")
    account["fees_krw"] = 0.0
    # V1 closed-trade records do not retain enough fee detail to reconstruct
    # historical cumulative fees exactly. Preserve net equity and mark the fee
    # history incomplete rather than presenting a fabricated total.
    account["fees_history_complete"] = False
    for item in old.get("closed", []):
        account["closed"].append({
            **copy.deepcopy(item),
            "opened_at": item.get("opened"), "closed_at": item.get("closed"),
            "side": "LONG" if item.get("side") == 1 else "SHORT",
            "entry_price": item.get("entry"), "exit_price": item.get("exit"),
            "net_pnl_krw": item.get("net_krw", item.get("net_pnl_krw", 0.0)),
            "entry_fee_krw": 0.0, "exit_fee_krw": 0.0,
        })
    pos = old.get("position")
    if pos:
        account["position"] = {
            "side": int(pos["side"]), "entry_price": _finite(pos["entry"], "legacy entry"),
            "notional_krw": _finite(pos["notional"], "legacy notional"),
            "entry_fee_krw": _finite(pos.get("fee", 0.0), "legacy position fee"),
            "opened_at": pos.get("at"), "reason": pos.get("reason"),
            "source_entry": pos.get("source_entry"), "entry_gap_pct": pos.get("entry_gap_pct"),
        }
        account["fees_krw"] += account["position"]["entry_fee_krw"]
    account["initialized"] = "fill_cursor" in old
    account["initial_krw"] = capital
    return account


def migrate_btc_ledger(old_ledger):
    """Convert the old BTC account schema and create a separate fresh ETH account."""
    if old_ledger.get("paper_only") is not True or old_ledger.get("real_trading_enabled") is not False:
        raise ValueError("Refusing non-PAPER legacy ledger")
    capital = old_ledger.get("initial_krw", INITIAL_KRW)
    wallets, snapshots = {}, {}
    for address, old_account in old_ledger.get("accounts", {}).items():
        wallet = address.lower()
        snapshots[wallet] = copy.deepcopy(old_account)
        wallets[wallet] = {
            "BTC": _migrate_legacy_btc_account(old_account, capital),
            "ETH": new_account(capital),
        }
    return {
        "schema_version": 2, "paper_only": True, "real_trading_enabled": False,
        "initial_krw_per_wallet_asset": capital,
        "leverage": old_ledger.get("leverage", LEVERAGE),
        "fee_rate": FEE_RATE, "slippage_rate": SLIPPAGE_RATE,
        "wallets": wallets, "legacy_btc_snapshot": snapshots,
        "legacy_btc_preserved": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
