#!/usr/bin/env python3
"""Build a compact BTC FLOW health/profit-source snapshot for PAPER monitoring."""
import datetime as dt
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "engine-status.json"


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main():
    category = load("trader-discovery/category-paper.json")
    catalog = load("trader-discovery/latest.json")
    whale = load("data/whale-paper-state.json")
    adaptive = load("data/adaptive-meta.json")

    rows = []
    for name, account in (category.get("accounts") or {}).items():
        fx = float(account.get("krw_per_usd") or 1500.0)
        net_krw = float(account.get("net_pnl_krw") or 0.0)
        unrealized_krw = float(account.get("unrealized_pnl_usd") or 0.0) * fx
        realized_krw = net_krw - unrealized_krw
        rows.append({
            "account": name,
            "category": account.get("category"),
            "leverage": account.get("leverage"),
            "starting_equity_krw": float(account.get("starting_equity_krw") or 0.0),
            "equity_krw": float(account.get("equity_krw") or 0.0),
            "net_pnl_krw": round(net_krw, 2),
            "realized_pnl_krw": round(realized_krw, 2),
            "unrealized_pnl_krw": round(unrealized_krw, 2),
            "open_count": int(account.get("open_count") or 0),
            "closed_count": int(account.get("closed_count") or 0),
            "return_pct": account.get("return_pct"),
        })

    total_start = sum(x["starting_equity_krw"] for x in rows)
    total_equity = sum(x["equity_krw"] for x in rows)
    total_net = sum(x["net_pnl_krw"] for x in rows)
    total_realized = sum(x["realized_pnl_krw"] for x in rows)
    total_unrealized = sum(x["unrealized_pnl_krw"] for x in rows)
    total_open = sum(x["open_count"] for x in rows)
    total_closed = sum(x["closed_count"] for x in rows)
    candidate_counts = catalog.get("candidate_counts") or {}
    current_candidates = sum(int(v or 0) for v in candidate_counts.values())

    if total_net > 0 and total_open == 0 and abs(total_unrealized) < 1:
        profit_source = "REALIZED_CLOSED_TRADES"
        reason_ko = "현재 열린 포지션이 없어 표시 중인 플러스 수익은 과거 종료 거래에서 확정된 누적 실현손익입니다."
    elif total_net > 0 and total_unrealized > 0 and total_realized > 0:
        profit_source = "MIXED_REALIZED_AND_UNREALIZED"
        reason_ko = "확정된 실현수익과 현재 열린 포지션의 미실현수익이 함께 플러스 수익에 반영되고 있습니다."
    elif total_net > 0 and total_unrealized > 0:
        profit_source = "UNREALIZED_OPEN_POSITIONS"
        reason_ko = "현재 열린 포지션의 평가이익이 플러스 수익의 주된 원인입니다."
    elif total_net > 0:
        profit_source = "REALIZED_OR_COST_ADJUSTED"
        reason_ko = "플러스 수익은 주로 종료 거래와 비용 반영 후 누적된 손익입니다."
    else:
        profit_source = "NO_POSITIVE_TOTAL_PNL"
        reason_ko = "6유형 PAPER 전체 합산 기준 현재 플러스 누적수익 상태가 아닙니다."

    payload = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "paper_only": True,
        "real_trading_enabled": False,
        "status": "OK",
        "category_catalog_generated_at": catalog.get("generated_at"),
        "current_candidate_counts": candidate_counts,
        "current_candidate_total": current_candidates,
        "six_category_summary": {
            "starting_equity_krw": round(total_start, 2),
            "equity_krw": round(total_equity, 2),
            "net_pnl_krw": round(total_net, 2),
            "realized_pnl_krw": round(total_realized, 2),
            "unrealized_pnl_krw": round(total_unrealized, 2),
            "open_positions": total_open,
            "closed_trades": total_closed,
            "profit_source": profit_source,
            "profit_reason_ko": reason_ko,
        },
        "accounts": rows,
        "legacy_whale_control": {
            "status": whale.get("status"),
            "open_positions": whale.get("open_positions"),
            "net_pnl_usd": (float(whale.get("estimated_equity_usd") or 0.0) - float(whale.get("starting_equity_usd") or 0.0)),
            "note": "Legacy control account; separate from the six 3,000,000 KRW / 10X category accounts.",
        },
        "adaptive": {
            "started_at": adaptive.get("started_at"),
            "paper_only": adaptive.get("paper_only"),
            "note": "Adaptive research accounts are separate from the six category accounts.",
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("ENGINE_STATUS=PASS", payload["six_category_summary"])


if __name__ == "__main__":
    main()
