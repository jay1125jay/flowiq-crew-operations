# Whale Tracker Data Sources

The whale module uses only Hyperliquid official/public data. It does not access Coin연 code, design, membership data, or restricted/private data.

## Official endpoints used

Base REST endpoint: `POST https://api.hyperliquid.xyz/info`

- `recentTrades` — public BTC trades used only to discover candidate public addresses.
- `clearinghouseState` — public account/position state used to verify account value, current BTC direction/size and entry price.
- `userFillsByTime` — public fills used for individual entry/add/partial-exit/full-exit/reversal points.
- `portfolio` — public PnL/account-value history and volume used for observation-period statistics and drawdown calculation.
- `candleSnapshot` — BTC 5-minute candles used by the mobile chart.
- `allMids` — BTC market price sampled after a new fills response is received; whale-follow paper trades use this post-detection price, not the whale's historical fill price.

## Official realtime method verified

Hyperliquid documents WebSocket at `wss://api.hyperliquid.xyz/ws` with subscriptions including `trades`, `userFills`, `clearinghouseState` and `candle`. The current BTC Flow server is an existing Postgres/pg_cron collector and therefore uses REST polling every minute; it must not be described as tick-level realtime.

## Rate-limit constraints checked

Hyperliquid documents an aggregate REST budget of 1200 weight/minute/IP. `clearinghouseState` and `allMids` have low weight; most other info requests have higher weight and user-fill requests add weight by returned item count. WebSocket connection/subscription/message limits also apply. The current collector limits active targets and runs the heavier portfolio statistics hourly.

## Fill/history limitations

Hyperliquid documents response/history limits for user fill queries. The collector backfills in repeated cursored windows using the last observed fill time and deduplicates on `(address, coin, tid)`.

## Labels

- `HISTORICAL`: fill occurred before this system began tracking the address. Never creates paper entries or alerts.
- `DELAYED`: fill is newer than the tracking start but too old for the configured fresh-signal window. Never creates a new paper entry.
- `LIVE_DETECTED`: fresh fill detected by the server. Paper processing is allowed only when the fill also has `market_price_timing=POST_RESPONSE_MARKET_PRICE`.

Funding cost for whale-follow paper testing is currently `UNVERIFIED` and is therefore shown separately rather than silently treated as zero.