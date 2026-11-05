#!/usr/bin/env python3
"""Reset only six BTC FLOW PC PAPER account balances, preserving trade history."""
import argparse
import copy
import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path

CATEGORIES = ("WHALE", "HIGH_WIN_RATE", "HIGH_PROFIT", "CONSISTENT", "SCALPER", "SWING")
KEYS = {f"{name}_10X" for name in CATEGORIES}
CAPITAL_KRW = 3_000_000


def _utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def reset_amounts(state, at):
    if state.get("paper_only") is not True or state.get("real_trading_enabled") is not False:
        raise ValueError("PAPER_ONLY_FLAG_INVALID")
    accounts = state.get("accounts")
    if state.get("account_count") != 6 or not isinstance(accounts, dict) or set(accounts) != KEYS:
        raise ValueError("EXPECTED_SIX_10X_ACCOUNTS")
    for key, account in accounts.items():
        if account.get("leverage") != 10 or account.get("starting_equity_krw") != CAPITAL_KRW:
            raise ValueError("CAPITAL_OR_LEVERAGE_MISMATCH:" + key)
        if account.get("positions"):
            raise ValueError("OPEN_POSITIONS_PRESENT:" + key)
        fx = float(account.get("krw_per_usd") or 0)
        if fx <= 0 or not 1000 <= fx <= 10000:
            raise ValueError("INVALID_TEST_FX:" + key)
    summary = {}
    for key, a in accounts.items():
        summary[key] = {
            "previous_equity_krw": a.get("equity_krw"),
            "previous_net_pnl_krw": a.get("net_pnl_krw"),
            "kept_closed_trades": len(a.get("closed", [])),
        }
        initial = CAPITAL_KRW / float(a["krw_per_usd"])
        a["cash"] = initial
        a["starting_equity_usd"] = initial
        a["starting_equity_krw"] = CAPITAL_KRW
        a["equity_usd"] = round(initial, 4)
        a["equity_krw"] = CAPITAL_KRW
        a["net_pnl_usd"] = 0.0
        a["net_pnl_krw"] = 0.0
        a["return_pct"] = 0.0
        a["unrealized_pnl_usd"] = 0.0
        a["margin_used_usd"] = 0.0
        a["margin_used_krw"] = 0.0
        a["free_equity_usd"] = round(initial, 4)
        a["free_equity_krw"] = CAPITAL_KRW
        a["total_notional_usd"] = 0.0
        a["total_notional_krw"] = 0.0
        a["cost_buffer_usd"] = 0.0
        a["cost_buffer_krw"] = 0.0
        a["remaining_execution_buffer_usd"] = 0.0
        a["remaining_execution_buffer_krw"] = 0.0
        a["fee_buffer_usd"] = 0.0
        a["fee_buffer_krw"] = 0.0
        a["allocation_capital_usd"] = initial
        a["allocation_target_count"] = 0
        a["peak"] = initial
        a["mdd_pct"] = 0.0
        # Preserve closed trades, trade statistics, account identity and tracking policy.
        a["amount_reset_at"] = at
    state["updated_at"] = at
    state.setdefault("capital_reset_history", []).append({
        "at": at,
        "reason": "USER_REQUEST_AMOUNT_ONLY",
        "amount_krw_per_account": CAPITAL_KRW,
        "prior_amounts": summary,
        "closed_trades_preserved": True,
    })
    return summary


def _hold_writer_lock(state_dir):
    lock_path = state_dir / "writer.lock"
    lock = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            lock.seek(0, 2)
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise RuntimeError("RUNNER_ACTIVE_STOP_BTC_FLOW_FIRST")
    return lock


def run(state_dir):
    state_dir = Path(state_dir).expanduser().resolve()
    path = state_dir / "category-paper-realtime.json"
    if not path.is_file():
        raise FileNotFoundError("PAPER_STATE_NOT_FOUND:" + str(path))
    with _hold_writer_lock(state_dir):
        original = path.read_bytes()
        payload = json.loads(original)
        if payload.get("version") != 1 or not isinstance(payload.get("state"), dict):
            raise ValueError("INVALID_PC_CATEGORY_STATE_WRAPPER")
        cloned = copy.deepcopy(payload)
        at = _utc_now()
        summary = reset_amounts(cloned["state"], at)
        backup = path.with_name("category-paper-realtime.pre-capital-reset-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
        shutil.copy2(path, backup)
        if backup.read_bytes() != original:
            raise RuntimeError("BACKUP_VERIFICATION_FAILED")
        tmp = path.with_suffix(".json.capital-reset.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fp:
                json.dump(cloned, fp, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
        verified = json.loads(path.read_text(encoding="utf-8"))["state"]
        if any(round(a["equity_krw"]) != CAPITAL_KRW or abs(a["net_pnl_krw"]) > 0.01 for a in verified["accounts"].values()):
            raise RuntimeError("POST_RESET_VERIFY_FAILED_RESTORE_BACKUP:" + str(backup))
        print("PASS: SIX_PC_PAPER_ACCOUNTS_RESET_TO_3000000_KRW")
        print("PASS: ALL_CLOSED_TRADES_PRESERVED")
        print("RESET_AT_UTC:", at)
        print("BACKUP:", backup)
        for key, a in verified["accounts"].items():
            print(key, "equity_krw=", a["equity_krw"], "net_pnl_krw=", a["net_pnl_krw"], "closed=", len(a.get("closed", [])))
        return summary


def main():
    parser = argparse.ArgumentParser()
    default = Path(os.getenv("LOCALAPPDATA") or ".") / "BTC_FLOW_PAPER" / "state"
    parser.add_argument("--state-dir", default=str(default))
    args = parser.parse_args()
    try:
        run(args.state_dir)
    except Exception as exc:
        print("FAIL:", type(exc).__name__, str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
