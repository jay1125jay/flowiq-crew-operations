# CASH FLOW V2 — BTC + ETH PAPER

## Implemented
- `cash_flow_v2_core.py`: independent BTC/ETH paper accounts per whale, fee/slippage accounting, liquidation, aggregate net PnL and legacy BTC migration.
- `wallet_paper_v2.py`: Hyperliquid REST recovery for BTC and ETH, independent L2 quotes and fill histories, baseline follow, same-timestamp overlap recovery, source-position chain validation and atomic V2 ledger writes.
- `pc_wallet_follow_v2.py`: real-time Hyperliquid userFills observer for both coins, reconnect, durable SQLite queue keyed by wallet+coin+tid, periodic REST recovery.
- `dashboard-v2.html`: BTC, ETH and aggregate PnL, whale/asset account table, fee and drawdown display, closed-trade history.
- `wallet_phone_v2.py`: read-only local and QR phone bridge for the V2 dashboard.
- Offline unit tests cover account isolation, fees, slippage, liquidation, migration, REST baseline, same-timestamp fills, quote validation, source gaps and phone view snapshots.

## Fixed PAPER parameters
- Initial capital: 1,000,000 KRW per whale per asset.
- Leverage: 10x paper notional.
- Fee: 0.05% per fill side.
- Slippage: 0.03%.
- BTC and ETH positions, source sizes, fill cursors, fee totals and closed histories are independent.
- Aggregate net PnL = total BTC+ETH equity minus total BTC+ETH initial capital.

## Data safety
- V2 writes only to `trader-discovery/wallet-paper-v2.json`; V1 BTC ledger is not overwritten.
- V2 queue is `pending-paper-v2.sqlite3`; V1 SQLite is not modified.
- Empty legacy BTC JSON causes migration to stop instead of creating replacement accounts.
- Exact raw legacy BTC account snapshots are retained in the V2 ledger.
- PAPER_ONLY is enforced. No exchange order, withdrawal or live execution endpoint is called.

## Validation
From `btc-flow-monitor`:
```powershell
python -m py_compile cash_flow_v2_core.py wallet_paper_v2.py pc_wallet_follow_v2.py wallet_phone_v2.py test_cash_flow_v2_core.py test_wallet_paper_v2.py test_wallet_phone_v2.py
python -m unittest -v test_cash_flow_v2_core.py test_wallet_paper_v2.py test_wallet_phone_v2.py
```

## Remaining before PC deployment
- GitHub Actions result and full local test execution.
- Windows launcher/supervisor with graceful V1 handoff, backup, health check and rollback.
- Windows PC acceptance test using the real BTC ledger and live WebSocket connection.
- Public GitHub Pages publication of V2 data. The phone QR bridge can serve the local V2 ledger once the V2 runner is installed.

Do not merge or install until CI and Windows acceptance tests pass. Existing PC engine remains untouched.
