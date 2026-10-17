# Trader Discovery — Research Registry v1

Status: PAPER_ONLY / RESEARCH_ONLY. No live orders. This registry is a collection plan, not evidence of a running collector.

## Scope
- Import **all** ranked wallets from `../data/whale-ranking.json`, not just paper candidates.
- Discover additional public Hyperliquid wallets from publicly documented, permitted discovery sources, with provenance, cursor, and deduplication.
- Research categories are non-exclusive: WHALE, HIGH_WIN_RATE, HIGH_PROFIT, CONSISTENT, SCALPER, SWING.
- Never label a wallet as skilled solely from an impressive short-window win rate or PnL.

## Minimum wallet record
wallet, source, discovered_at, first_seen_at, last_seen_at, history_coverage_start/end, history_is_capped, fill_count, closed_trade_count, realized_net_pnl, fees, estimated_funding, win_rate, profit_factor, max_drawdown, median_holding_seconds, p90_holding_seconds, median_notional, median_leverage, trade_frequency_per_day, largest_win_share, forward_days, forward_closes, forward_net_pnl_after_costs, classification, confidence, last_successful_refresh_at, errors.

## Strategy classification (provisional, must calibrate)
- SCALPER: at least 30 complete round-trip trades; median holding <= 15 minutes; majority of trades close within 60 minutes.
- SWING: at least 20 complete round-trip trades; median holding >= 4 hours; majority of trades held >= 1 hour.
- OTHER / INSUFFICIENT_DATA / MIXED: otherwise. Account for partial closes, same-direction adds, reversals, fees, funding and missing historical fills.
- Never infer holding time from fills without robust trade reconstruction.

## Validation
1. Snapshot the source data, mark any truncated historical sample.
2. Reconstruct trades without look-ahead, with fill IDs and time cursor deduplication.
3. Classify using history only; require a separate forward evaluation window.
4. Simulate independent SCALP and SWING paper accounts with signal-observation latency, realistic fees, slippage and funding.
5. Compare against buy-and-hold, random-entry and simple momentum baselines. Include zero-trade and failed-fetch outcomes.
6. Report sample size, confidence interval, drawdown, turnover, execution lag, and profitability after costs.
7. Explicitly label all unverified candidates; never enable live orders.

## Initial verified repository snapshot
At 2026-10-17T10:46:33Z `whale-ranking.json` contained 8 ranked wallets, 5 paper candidates and 0 verified wallets. This is a historical snapshot, not a live counter.

## Deployment
The GitHub Actions polling pipeline is separate from the planned Google Cloud WebSocket server. Do not claim the real-time collector is running until VM deployment, health checks and persisted signals are verified.
