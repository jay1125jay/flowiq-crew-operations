# CASH FLOW V2 — BTC + ETH PAPER

## Implemented
- `cash_flow_v2_core.py`: independent BTC/ETH paper accounts per whale, fee/slippage accounting, liquidation, aggregate net PnL and legacy BTC migration.
- `wallet_paper_v2.py`: Hyperliquid REST recovery for BTC and ETH, independent L2 quotes and fill histories, baseline follow, same-timestamp overlap recovery, source-position chain validation and atomic V2 ledger writes.
- `pc_wallet_follow_v2.py`: real-time Hyperliquid userFills observer for both coins, reconnect, durable SQLite queue keyed by wallet+coin+tid, periodic REST recovery and graceful stop signal.
- `dashboard-v2.html`: BTC, ETH and aggregate PnL, whale/asset account table, fee and drawdown display, closed-trade history.
- `wallet_phone_v2.py`: read-only local and QR phone bridge for the V2 dashboard.
- `CASH_FLOW_V2_SUPERVISOR.ps1`: test-before-update supervisor, graceful engine handoff, V2 data backup, health check and automatic rollback.
- `START_CASH_FLOW_V2.cmd`: one-click bootstrap for the supervisor.
- Offline tests cover accounting, migration, REST snapshots, fill ordering, source gaps and phone view snapshots.

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
- First migration fetches the latest `main` BTC ledger; empty data or changed whale selection causes a hard stop.
- Exact raw legacy BTC account snapshots are retained in the V2 ledger.
- V1 closed trades do not contain enough data to reconstruct all historical fees; the BTC fee total is explicitly marked incomplete. Existing BTC net equity and realized PnL are preserved.
- Automatic update tests the candidate version first, backs up V2 data, stops V2 gracefully, checks health and rolls back on failure.
- PAPER_ONLY is enforced. No exchange order, withdrawal or live execution endpoint is called.

## Validation
From `btc-flow-monitor`:
```powershell
python -m py_compile cash_flow_v2_core.py wallet_paper_v2.py pc_wallet_follow_v2.py wallet_phone_v2.py test_cash_flow_v2_core.py test_wallet_paper_v2.py test_wallet_phone_v2.py
python -m unittest -v test_cash_flow_v2_core.py test_wallet_paper_v2.py test_wallet_phone_v2.py
```

## Before first PC launch
- V1 and V2 must not run together because they subscribe to the same whale fills and share exchange API limits.
- Close the V1 engine window gracefully with Ctrl+C once. The supervisor refuses to force-kill it.
- Run `START_CASH_FLOW_V2.cmd`; it creates a separate V2 folder and Python environment.
- After first launch, code updates are checked automatically every 60 seconds. No PC reboot is required for updates.
- Keep the supervisor window open and keep the PC online.
- Windows acceptance test and real local BTC ledger migration must pass before replacing V1 permanently.

## Deployment state
Draft only. Existing PC engine and main BTC ledger have not been changed. Do not merge or install until Python CI and Windows PowerShell syntax checks pass.
