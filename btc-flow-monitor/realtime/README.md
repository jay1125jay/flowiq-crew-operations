# BTC FLOW realtime PAPER runner

Status: deployment preparation. No Google Cloud resource is created by these files.
Existing GitHub cron, historical whale control and 12 category accounts remain intact.
The realtime runner has six new, equal-capital PAPER accounts in a separate epoch.
Never combine these results with the historical five-minute experiment.

## Timing and safety

- BTC public BBO WebSocket: event-driven. Evaluate at a one-second target interval.
- Cohorts, wallet directions, funding, OI and CLOSED five-minute candles: a complete
  public REST collection cycle targeted every 60 seconds. This is NOT one-second
  whale-position visibility. Old wallet observations are bounded using cycle start.
- Price >5 seconds old, incomplete collection, source >120 seconds old, invalid data
  or disconnected stream blocks all ledger advancement. Existing positions remain
  open and are revalued when observations resume; no fictitious backfilled trades.
- Duplicate/out-of-order quotes do not execute twice; no catch-up burst after lag.
- Derivatives compare distinct source snapshots, not repeated evaluations of one
  snapshot. Funding retains the previous hourly-rate sampled estimate.
- Shared risk/cost rules come from adaptive_meta.py. Confidence is signal strength,
  not a calibrated win probability. Profitability remains UNPROVEN.
- Original SWING 60-minute hold / two post-hold reversal observations stay in the
  original category engine. The six-engine runtime does not pretend to run those
  additional 12 category accounts at one-second cadence.

## Durable single-host execution

Linux/Python 3.12, one process, one persistent LOCAL disk (not network SQLite).
SQLite WAL + FULL synchronization commits balances and dedup cursor together.
A process lock rejects a second writer using the same state directory.
Corrupt state is an error, never an automatic capital reset. The isolated collector
keeps its forward evidence across restarts. Do not delete or recreate the disk.
All state stays outside Git; no GitHub credential or exchange key is required.

From the repository root:

```sh
python -m pip install -r btc-flow-monitor/realtime/requirements.txt
PAPER_ONLY=true REAL_TRADING=false python btc-flow-monitor/realtime_runtime.py \
  --state-dir /var/lib/btc-flow-paper --host 127.0.0.1 --port 8080
```

`/` is the realtime comparison page; `/api/status` is read-only JSON; `/healthz`
returns 503 while disconnected, stale or warming up. No order/admin HTTP endpoint.
The UI polls once per second AFTER each response; actual refresh can take longer.
Its displayed signals become WAIT when health is stale or disconnected.

Container (repository root is the build context):

```sh
docker build -f btc-flow-monitor/realtime/Dockerfile -t btc-flow-paper .
docker volume create btc-flow-paper-state
docker run --name btc-flow-paper --restart unless-stopped \
  -p 127.0.0.1:8080:8080 -v btc-flow-paper-state:/state btc-flow-paper
```

Google deployment target: one Compute Engine VM with durable disk, not an ephemeral
Cloud Run filesystem or a five-minute Scheduler. Project ID, billing choice,
region, HTTPS endpoint and phone access will be configured at deployment time.
Do not open the raw HTTP port publicly; use a TLS reverse proxy. Back up the SQLite
DB using its online backup API (copying a live WAL database file alone is unsafe).
No cloud deployment, always-on uptime or exact one-second latency is claimed yet.

## Verification

```sh
python -m unittest discover -s btc-flow-monitor -p 'test_*.py' -v
PAPER_ONLY=true REAL_TRADING=false python btc-flow-monitor/verify_realtime_live.py
```

CI uses disposable accounts for a 90-second public-data smoke test and keeps its
JSON evidence. Browser CI tests desktop/mobile layout, stale signals and HTTP errors
with labelled synthetic fixtures. Neither test evidence is a profitability result.

Public protocol reference:
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/timeouts-and-heartbeats
