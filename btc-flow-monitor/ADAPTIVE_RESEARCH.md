# BTC FLOW forward PAPER competition v3

## Audit baseline

- Main inspected: `a72da0a3cb85c4a937e0681a6f40fa16c13dd233`.
- Run #87 / 39261078213: success, confirmed with GitHub API.
- Run #94 / 39373583778: failure. Job 118466620102 logs show `KeyError: 'cash'` when signal-only schema 1 accounts were treated as executable ledgers.
- Schema 3 archives the entire previous adaptive snapshot inside `legacy_snapshot`. A new common-capital epoch begins at its first valid live observation. Old signal history is never represented as executed trades.
- Original whale follower code/accounts and the twelve cohort accounts are preserved. SWING retains its 60-minute minimum hold, two post-hold opposite observations and no same-cycle reverse entry.

## Competition

Six independent accounts start at $1,000 each, with $500 maximum entry notional and 50% equity exposure cap, 1x comparison leverage, 5 bps fees and 3 bps slippage on each side. Existing 2x/5x/10x experiments are separate.

WHALE_COPY preserves the original top-three candidate selection and baseline-then-direction-change behavior, with normalized exposure split across three slots. The original whale-paper-state.json remains the unchanged legacy control; its historical leverage returns are not directly comparable to the new epoch.

SMART_MONEY aggregates classified traders only, downweights stale classifications, and shrinks observed trader performance toward a neutral prior. MARKET_STRUCTURE uses closed 5-minute OHLCV bars. DERIVATIVES uses observed funding and open interest; OI growth alone does not imply upward price direction. FIXED_ENSEMBLE uses 40/40/20 weights. ADAPTIVE_META uses lifetime, recent and entry-regime net trade results. Components retain a neutral quality prior below 30 completed trades, shrink beyond that, and weights move at most one percentage point per new completed-trade evaluation. Repeated polling without new completed trades cannot move weights.

Each account stores all closed trades, fees, sampled funding, liquidation count, open PnL, net PnL, return, trade expectancy, profit factor, sampled maximum drawdown, return/drawdown, win rate, mean win/loss and entry-regime metrics. No truncation of the new trade ledger. PF is null when undefined, with a separate status; it is not fabricated as 99 or Infinity.

## Data and limitations

Only public Hyperliquid `/info` requests are used. Sources:
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits

Market inputs are collected before the shared position/price observation. Closed candles must be ordered, contiguous and fresh. Errors, missing wallets, stale/future timestamps, missing safety flags and nonfinite values block publication. Repeated position timestamps are idempotent; older timestamps are rejected.

Funding cost is an estimate using the previously observed hourly rate, elapsed time and current mark, not exact historical settlements. Observation gaps can misestimate funding. Liquidations and drawdowns are sampled, and intrainterval moves can be missed. Market-wide liquidations and long/short positioning are explicitly unavailable, not zero-valued fake feeds. Signal confidence is strength, not calibrated win probability. Whale observations are sequential API samples, not simultaneous exchange snapshots.

The five-minute cron is requested, not guaranteed by GitHub scheduling. The dashboard marks observations older than 15 minutes as delayed and suppresses actionable current direction. Rebase/push retries never force-push; overlapping research edits fail rather than overwrite data. Tests and all account/freshness checks run before persistence.

PAPER_ONLY=true; REAL_TRADING=false. No order, deposit, withdrawal or signing implementation. Profitability is UNPROVEN until sufficient independent forward observations, costs and uncertainty have been reviewed. Positive early PnL is not proof.
