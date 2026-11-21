# CASH FLOW V2 — BTC + ETH PAPER

## Implemented in this branch
- `cash_flow_v2_core.py`: isolated BTC/ETH accounts, fee/slippage accounting, liquidation, aggregate net PnL, legacy BTC conversion.
- `wallet_paper_v2.py`: Hyperliquid REST reconciliation for BTC and ETH, per-coin books/fills, snapshot baseline, atomic V2 ledger writes.
- `pc_wallet_follow_v2.py`: Hyperliquid userFills WebSocket observer for both coins, SQLite pending queue with UNIQUE(wallet, coin, tid), replay/reconnect, periodic REST reconciliation.
- Offline unit tests for core accounting, migration, BTC/ETH isolation, same-time fills, quote validation and source-chain gaps.

## Fixed PAPER parameters
- Starting capital: 1,000,000 KRW per whale per asset.
- Leverage: 10x paper notional.
- Fee: 0.05% per fill side.
- Slippage: 0.03%.
- BTC and ETH positions, fill cursors, source sizes, histories and fee totals are independent.
- Aggregate net PnL = sum of all BTC and ETH account equity minus total initial capital.

## Data safety
- V2 writes to `trader-discovery/wallet-paper-v2.json`; it never overwrites the existing BTC ledger.
- Pending events use a separate `pending-paper-v2.sqlite3`; the V1 queue is not migrated or modified.
- If the legacy BTC JSON exists but is empty, migration aborts rather than creating replacement accounts.
- Legacy BTC account data is retained as an exact snapshot in the V2 ledger.
- PAPER_ONLY is enforced. No exchange order, withdrawal or live execution endpoint is called.

## Validation
From `btc-flow-monitor`:
```powershell
python -m py_compile cash_flow_v2_core.py wallet_paper_v2.py pc_wallet_follow_v2.py test_cash_flow_v2_core.py test_wallet_paper_v2.py
python -m unittest -v test_cash_flow_v2_core.py test_wallet_paper_v2.py
```

## Not production-ready yet
- Dashboard UI still needs V2 BTC/ETH cards and aggregate PnL wiring.
- Phone API still serves the V1 schema; V2 read-only integration is pending.
- Safe Windows installer/updater, process handoff, backup/rollback and PC acceptance test are pending.
- This branch must not be merged or installed until CI and Windows acceptance tests pass.
