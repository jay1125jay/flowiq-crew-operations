#!/usr/bin/env python3
"""Read public Hyperliquid /info only. No signing, credentials or orders."""
import datetime as dt
import json
import pathlib
import time
import urllib.request
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parent
API = 'https://api.hyperliquid.xyz/info'

def api(payload):
    if payload['type'] not in ('metaAndAssetCtxs', 'candleSnapshot'):
        raise ValueError('read-only request whitelist')
    for attempt in range(3):
        try:
            request = urllib.request.Request(API, data=json.dumps(payload).encode(),
                headers={'Content-Type':'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=25) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2**attempt)

def main():
    now = dt.datetime.now(dt.timezone.utc)
    end = int(now.timestamp()*1000)
    meta, contexts = api({'type':'metaAndAssetCtxs'})
    i = next(i for i,x in enumerate(meta['universe']) if x['name']=='BTC')
    ctx = contexts[i]
    candles = api({'type':'candleSnapshot', 'req':{'coin':'BTC','interval':'5m',
                   'startTime':end-25*300000,'endTime':end}})
    candles = sorted((c for c in candles if int(c['T']) < end), key=lambda c:int(c['T']))[-24:]
    out = dict(schema_version=1, paper_only=True, real_trading_enabled=False,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(), source='hyperliquid_public_info',
        funding_rate=float(ctx['funding']), open_interest_btc=float(ctx['openInterest']),
        reference_price=float(ctx.get('midPx') or ctx['markPx']), candles=candles, errors=[],
        unavailable=['market_wide_liquidations','market_wide_long_short_ratio'])
    path = ROOT/'data/adaptive-market.json'
    path.with_suffix('.tmp').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
    path.with_suffix('.tmp').replace(path)
    print('PUBLIC MARKET PASS closed_candles=',len(candles))

if __name__ == '__main__':
    main()
