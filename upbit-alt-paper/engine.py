from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "data" / "state.json"
API = "https://api.upbit.com/v1"
KST = timezone(timedelta(hours=9))
STRATEGY_VERSION = "v2_BREAKOUT_CONFIRM"

SETTINGS = {
    "starting_capital": 1_000_000.0,
    "fee_rate": 0.0005,
    "slippage_rate": 0.001,
    "allocation_per_trade": 100_000.0,
    "max_positions": 3,
    "stop_loss_pct": 3.5,
    "trailing_pct": 3.0,
    "take_profit_pct": 12.0,
    "max_hold_hours": 12,
    "cooldown_minutes": 60,
    "candidate_min_change_pct": 2.0,
    "candidate_max_change_pct": 10.0,
    "candidate_min_trade_value_24h": 2_000_000_000.0,
    "deep_scan_limit": 25,
    "display_candidate_limit": 15,
    "breakout_buffer_pct": 0.2,
    "breakout_retest_tolerance_pct": 0.5,
    "max_breakout_extension_pct": 2.0,
    "min_breakout_volume_ratio": 1.5,
    "max_breakout_candle_pct": 4.0,
}


def now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def api_get(path: str):
    req = urllib.request.Request(
        f"{API}{path}",
        headers={"Accept": "application/json", "User-Agent": "UPBIT-ALT-PAPER/2.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(state, dict):
                return state
        except Exception:
            pass
    return {
        "version": 1,
        "paper_only": True,
        "strategy_version": STRATEGY_VERSION,
        "updated_at": None,
        "settings": SETTINGS.copy(),
        "account": {
            "cash": SETTINGS["starting_capital"],
            "realized_pnl": 0.0,
            "equity": SETTINGS["starting_capital"],
            "unrealized_pnl": 0.0,
            "return_pct": 0.0,
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
        },
        "candidates": [],
        "positions": [],
        "trades": [],
        "cooldowns": {},
        "engine": {
            "status": "INIT",
            "markets_scanned": 0,
            "candidates_found": 0,
            "entries": 0,
            "exits": 0,
            "cycle_ms": 0,
            "error": None,
        },
    }


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def chunks(values: list[str], size: int):
    for i in range(0, len(values), size):
        yield values[i : i + size]


def fetch_tickers(markets: list[str]) -> list[dict]:
    out: list[dict] = []
    for group in chunks(markets, 80):
        query = urllib.parse.quote(",".join(group), safe=",")
        out.extend(api_get(f"/ticker?markets={query}"))
        time.sleep(0.12)
    return out


def calc_rsi14(candles_newest_first: list[dict]) -> float:
    closes = [float(c["trade_price"]) for c in candles_newest_first[:40]][::-1]
    if len(closes) < 15:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(len(closes) - 14, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses += abs(diff)
    avg_gain = gains / 14
    avg_loss = losses / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def analyze_candidate(ticker: dict, meta: dict, btc_change: float) -> dict:
    market = ticker["market"]
    candles = api_get(f"/candles/minutes/15?market={market}&count=80")
    time.sleep(0.12)
    days = api_get(f"/candles/days?market={market}&count=8")
    time.sleep(0.12)

    completed_days = days[1:8]
    avg_daily_value = (
        sum(float(c.get("candle_acc_trade_price", 0.0)) for c in completed_days) / len(completed_days)
        if completed_days
        else float(ticker.get("acc_trade_price_24h", 0.0))
    )
    trade_value_24h = float(ticker.get("acc_trade_price_24h", 0.0))
    volume_ratio = trade_value_24h / avg_daily_value if avg_daily_value > 0 else 0.0

    # RSI는 진행 중인 현재 15분봉을 제외하고 계산한다.
    rsi = calc_rsi14(candles[1:])

    # 진입 판단은 진행 중 봉(candles[0])이 아니라 직전 마감봉(candles[1])으로 확정한다.
    breakout_candle = candles[1]
    resistance_window = candles[2:22]
    breakout = (
        max(float(c["high_price"]) for c in resistance_window)
        if resistance_window
        else float(ticker["trade_price"])
    )
    support_window = candles[2:14]
    support = (
        min(float(c["low_price"]) for c in support_window)
        if support_window
        else float(ticker["trade_price"])
    )

    bo_open = float(breakout_candle["opening_price"])
    bo_high = float(breakout_candle["high_price"])
    bo_low = float(breakout_candle["low_price"])
    bo_close = float(breakout_candle["trade_price"])
    bo_range = max(bo_high - bo_low, 1e-12)
    bo_upper_wick = bo_high - max(bo_open, bo_close)
    upper_wick_risk = bo_upper_wick / bo_range >= 0.50
    breakout_candle_pct = ((bo_close - bo_open) / bo_open * 100.0) if bo_open > 0 else 0.0

    history_for_volume = candles[2:14]
    avg_15m_value = (
        sum(float(c.get("candle_acc_trade_price", 0.0)) for c in history_for_volume) / len(history_for_volume)
        if history_for_volume
        else 0.0
    )
    breakout_value = float(breakout_candle.get("candle_acc_trade_price", 0.0))
    breakout_volume_ratio = breakout_value / avg_15m_value if avg_15m_value > 0 else 0.0

    price = float(ticker["trade_price"])
    day_high = float(ticker.get("high_price", price))
    collapse_risk = day_high > 0 and price <= day_high * 0.90
    change_pct = float(ticker.get("signed_change_rate", 0.0)) * 100.0

    buffer = SETTINGS["breakout_buffer_pct"] / 100.0
    retest_tolerance = SETTINGS["breakout_retest_tolerance_pct"] / 100.0
    breakout_close_confirmed = bo_close >= breakout * (1.0 + buffer)
    breakout_volume_confirmed = breakout_volume_ratio >= SETTINGS["min_breakout_volume_ratio"]
    price_holds_breakout = price >= breakout * (1.0 - retest_tolerance)
    breakout_distance_pct = ((price - breakout) / breakout * 100.0) if breakout > 0 else 0.0
    overextended = (
        breakout_distance_pct > SETTINGS["max_breakout_extension_pct"]
        or breakout_candle_pct > SETTINGS["max_breakout_candle_pct"]
    )

    score = 10
    score += 20 if volume_ratio >= 3 else 12 if volume_ratio >= 2 else 6 if volume_ratio >= 1.5 else 0
    score += 15 if 50 <= rsi <= 68 else 8 if 45 <= rsi <= 72 else 0
    score += 20 if breakout_close_confirmed else 8 if price >= breakout * 0.98 else 0
    score += 10 if breakout_volume_confirmed else 4 if breakout_volume_ratio >= 1.1 else 0
    score += 10 if trade_value_24h >= 10_000_000_000 else 6 if trade_value_24h >= 5_000_000_000 else 2
    score += 10 if btc_change > -0.02 else 4 if btc_change > -0.04 else 0
    score += 5 if price_holds_breakout else 0
    if upper_wick_risk:
        score -= 15
    if collapse_risk:
        score -= 15
    if overextended:
        score -= 20
    score = int(max(0, min(100, round(score))))

    hard_trigger = (
        score >= 80
        and volume_ratio >= 3
        and 50 <= rsi <= 68
        and breakout_close_confirmed
        and breakout_volume_confirmed
        and price_holds_breakout
        and not overextended
        and not upper_wick_risk
        and not collapse_risk
    )
    status = "TRIGGER" if hard_trigger else "WATCH" if score >= 70 else "EARLY"

    return {
        "market": market,
        "symbol": market.replace("KRW-", ""),
        "korean_name": meta.get("korean_name", market),
        "price": round(price, 8),
        "change_pct": round(change_pct, 4),
        "trade_value_24h": round(trade_value_24h, 2),
        "volume_ratio": round(volume_ratio, 3),
        "rsi14": round(rsi, 2),
        "breakout_price": round(breakout, 8),
        "support_price": round(support, 8),
        "score": score,
        "status": status,
        "upper_wick_risk": upper_wick_risk,
        "collapse_risk": collapse_risk,
        "breakout_confirmed": breakout_close_confirmed,
        "breakout_volume_confirmed": breakout_volume_confirmed,
        "price_holds_breakout": price_holds_breakout,
        "overextended": overextended,
        "breakout_volume_ratio": round(breakout_volume_ratio, 3),
        "breakout_distance_pct": round(breakout_distance_pct, 3),
        "breakout_candle_pct": round(breakout_candle_pct, 3),
    }


def portfolio_metrics(state: dict, ticker_map: dict[str, dict]) -> None:
    fee_rate = float(SETTINGS["fee_rate"])
    cash = float(state["account"].get("cash", SETTINGS["starting_capital"]))
    unrealized = 0.0
    marked_value = 0.0

    for position in state.get("positions", []):
        ticker = ticker_map.get(position["market"])
        if not ticker:
            continue
        current_price = float(ticker["trade_price"])
        position["current_price"] = round(current_price, 8)
        gross = current_price * float(position["quantity"])
        exit_fee = gross * fee_rate
        net_value = gross - exit_fee
        marked_value += net_value
        basis = float(position["cost_basis"]) + float(position["entry_fee"])
        pnl = net_value - basis
        pnl_pct = (pnl / basis * 100.0) if basis > 0 else 0.0
        position["unrealized_pnl"] = round(pnl, 2)
        position["pnl_pct"] = round(pnl_pct, 3)
        unrealized += pnl

    equity = cash + marked_value
    start = float(SETTINGS["starting_capital"])
    return_pct = ((equity - start) / start * 100.0) if start > 0 else 0.0
    closed = [t for t in state.get("trades", []) if t.get("side") == "SELL"]
    wins = sum(1 for t in closed if float(t.get("pnl", 0.0)) > 0)
    losses = sum(1 for t in closed if float(t.get("pnl", 0.0)) <= 0)
    trades = len(closed)

    state["account"].update(
        {
            "equity": round(equity, 2),
            "unrealized_pnl": round(unrealized, 2),
            "return_pct": round(return_pct, 3),
            "trades": trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / trades * 100.0) if trades else 0.0, 2),
        }
    )


def execute_cycle(state: dict) -> dict:
    started = time.time()
    entries = 0
    exits = 0

    markets = api_get("/market/all?isDetails=false")
    krw_meta = {m["market"]: m for m in markets if m["market"].startswith("KRW-")}
    krw_markets = list(krw_meta.keys())
    tickers = fetch_tickers(krw_markets)
    ticker_map = {t["market"]: t for t in tickers}
    btc_change = float(ticker_map.get("KRW-BTC", {}).get("signed_change_rate", 0.0))

    min_change = SETTINGS["candidate_min_change_pct"] / 100.0
    max_change = SETTINGS["candidate_max_change_pct"] / 100.0
    shortlist = [
        t
        for t in tickers
        if t["market"] != "KRW-BTC"
        and min_change <= float(t.get("signed_change_rate", 0.0)) < max_change
        and float(t.get("acc_trade_price_24h", 0.0)) >= SETTINGS["candidate_min_trade_value_24h"]
    ]
    shortlist.sort(key=lambda x: float(x.get("acc_trade_price_24h", 0.0)), reverse=True)
    shortlist = shortlist[: SETTINGS["deep_scan_limit"]]

    candidates = []
    errors = []
    for ticker in shortlist:
        try:
            candidates.append(analyze_candidate(ticker, krw_meta.get(ticker["market"], {}), btc_change))
        except Exception as exc:
            errors.append(f"{ticker['market']}: {exc}")
    candidates.sort(key=lambda x: (x["score"], x["trade_value_24h"]), reverse=True)
    state["candidates"] = candidates[: SETTINGS["display_candidate_limit"]]

    fee_rate = SETTINGS["fee_rate"]
    slippage = SETTINGS["slippage_rate"]
    cash = float(state["account"].get("cash", SETTINGS["starting_capital"]))
    realized = float(state["account"].get("realized_pnl", 0.0))

    remaining_positions = []
    for p in state.get("positions", []):
        ticker = ticker_map.get(p["market"])
        if not ticker:
            remaining_positions.append(p)
            continue

        market_price = float(ticker["trade_price"])
        entry = float(p["entry_price"])
        highest = max(float(p.get("highest_price", entry)), market_price)
        p["highest_price"] = round(highest, 8)

        stop_hit = market_price <= float(p["stop_price"])
        trail_armed = highest >= entry * 1.05
        trail_hit = trail_armed and market_price <= highest * (1.0 - SETTINGS["trailing_pct"] / 100.0)
        take_profit = market_price >= entry * (1.0 + SETTINGS["take_profit_pct"] / 100.0)
        opened_at = parse_iso(p.get("opened_at"))
        max_hold = bool(opened_at and datetime.now(KST) - opened_at >= timedelta(hours=SETTINGS["max_hold_hours"]))

        if stop_hit or trail_hit or take_profit or max_hold:
            reason = (
                "STOP / 손절"
                if stop_hit
                else "TP / 목표익절"
                if take_profit
                else "TRAIL / 추적청산"
                if trail_hit
                else "TIME / 최대보유시간"
            )
            exit_price = market_price * (1.0 - slippage)
            quantity = float(p["quantity"])
            gross = exit_price * quantity
            fee = gross * fee_rate
            proceeds = gross - fee
            basis = float(p["cost_basis"]) + float(p["entry_fee"])
            pnl = proceeds - basis
            pnl_pct = pnl / basis * 100.0 if basis > 0 else 0.0
            cash += proceeds
            realized += pnl
            exits += 1
            closed_at = now_iso()
            state["trades"].append(
                {
                    "time": closed_at,
                    "market": p["market"],
                    "symbol": p["symbol"],
                    "side": "SELL",
                    "price": round(exit_price, 8),
                    "quantity": round(quantity, 12),
                    "gross_value": round(gross, 2),
                    "fee": round(fee, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 3),
                    "reason": reason,
                    "strategy_version": p.get("strategy_version", "v1_LEGACY"),
                }
            )
            state["cooldowns"][p["market"]] = closed_at
        else:
            remaining_positions.append(p)

    state["positions"] = remaining_positions
    open_markets = {p["market"] for p in remaining_positions}

    def cooldown_active(market: str) -> bool:
        closed = parse_iso(state.get("cooldowns", {}).get(market))
        return bool(closed and datetime.now(KST) - closed < timedelta(minutes=SETTINGS["cooldown_minutes"]))

    if len(remaining_positions) < SETTINGS["max_positions"]:
        trigger = next(
            (
                c
                for c in candidates
                if c["status"] == "TRIGGER"
                and c.get("breakout_confirmed")
                and c.get("breakout_volume_confirmed")
                and c.get("price_holds_breakout")
                and not c.get("overextended")
                and c["market"] not in open_markets
                and not cooldown_active(c["market"])
            ),
            None,
        )
        if trigger and cash >= 50_000:
            allocation = min(SETTINGS["allocation_per_trade"], cash * 0.15)
            entry_price = float(trigger["price"]) * (1.0 + slippage)
            gross = allocation / (1.0 + fee_rate)
            fee = gross * fee_rate
            quantity = gross / entry_price
            opened_at = now_iso()
            position = {
                "market": trigger["market"],
                "symbol": trigger["symbol"],
                "korean_name": trigger["korean_name"],
                "entry_price": round(entry_price, 8),
                "current_price": round(float(trigger["price"]), 8),
                "quantity": round(quantity, 12),
                "cost_basis": round(gross, 2),
                "entry_fee": round(fee, 2),
                "stop_price": round(entry_price * (1.0 - SETTINGS["stop_loss_pct"] / 100.0), 8),
                "highest_price": round(entry_price, 8),
                "trailing_pct": SETTINGS["trailing_pct"],
                "entry_score": trigger["score"],
                "opened_at": opened_at,
                "unrealized_pnl": 0.0,
                "pnl_pct": 0.0,
                "strategy_version": STRATEGY_VERSION,
                "breakout_price": trigger["breakout_price"],
                "breakout_volume_ratio": trigger["breakout_volume_ratio"],
            }
            state["positions"].append(position)
            state["trades"].append(
                {
                    "time": opened_at,
                    "market": trigger["market"],
                    "symbol": trigger["symbol"],
                    "side": "BUY",
                    "price": round(entry_price, 8),
                    "quantity": round(quantity, 12),
                    "gross_value": round(gross, 2),
                    "fee": round(fee, 2),
                    "pnl": 0.0,
                    "pnl_pct": 0.0,
                    "reason": f"CONFIRMED BREAKOUT {trigger['score']}",
                    "strategy_version": STRATEGY_VERSION,
                }
            )
            cash -= gross + fee
            entries += 1

    state["account"]["cash"] = round(cash, 2)
    state["account"]["realized_pnl"] = round(realized, 2)
    state["trades"] = state["trades"][-120:]

    portfolio_metrics(state, ticker_map)
    elapsed_ms = int((time.time() - started) * 1000)
    state["updated_at"] = now_iso()
    state["paper_only"] = True
    state["strategy_version"] = STRATEGY_VERSION
    state["settings"] = SETTINGS.copy()
    state["engine"] = {
        "status": "PASS" if not errors else "PARTIAL",
        "markets_scanned": len(krw_markets),
        "candidates_found": len(candidates),
        "entries": entries,
        "exits": exits,
        "cycle_ms": elapsed_ms,
        "error": errors[:5] if errors else None,
    }
    return state


def main() -> None:
    state = load_state()
    try:
        state = execute_cycle(state)
    except Exception as exc:
        state["updated_at"] = now_iso()
        state["engine"] = {
            "status": "FAIL",
            "markets_scanned": state.get("engine", {}).get("markets_scanned", 0),
            "candidates_found": len(state.get("candidates", [])),
            "entries": 0,
            "exits": 0,
            "cycle_ms": 0,
            "error": str(exc),
        }
        save_state(state)
        raise
    save_state(state)
    print(json.dumps({
        "status": state["engine"]["status"],
        "strategy_version": state.get("strategy_version"),
        "updated_at": state["updated_at"],
        "candidates": len(state["candidates"]),
        "positions": len(state["positions"]),
        "equity": state["account"]["equity"],
        "return_pct": state["account"]["return_pct"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
