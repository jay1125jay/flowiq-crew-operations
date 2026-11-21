# CASH FLOW V2 — BTC + ETH PAPER core

This branch adds an isolated accounting core. It does not replace the running PC engine.

## Fixed rules
- PAPER ONLY. No order placement, exchange trading endpoints, withdrawals, or live execution.
- Per whale and per asset: 1,000,000 KRW starting equity, 10x leverage.
- BTC and ETH have separate positions, fill cursors, fees, and closed-trade histories.
- Aggregate net PnL is the sum of all BTC and ETH account equity minus their initial equity.
- Fee rate 0.05% and slippage 0.03% are included in account equity.
- Legacy BTC account objects are deep-copied unchanged by the migration helper; ETH starts as a new independent paper account.

## Files
- cash_flow_v2_core.py: deterministic accounting/migration/aggregation functions.
- test_cash_flow_v2_core.py: offline tests; no network calls.

## Validation
Run:
```powershell
python -m unittest -v test_cash_flow_v2_core.py
```

## Not yet production-integrated
The live WebSocket observer, REST recovery, SQLite pending queue, phone view, and dashboard still require a coordinated BTC+ETH integration and Windows acceptance test. Do not install this core as a replacement engine yet.
