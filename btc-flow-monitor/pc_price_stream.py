#!/usr/bin/env python3
"""PC BTC public-price stream with Hyperliquid WebSocket primary and REST fallback.

PAPER research only. This module never sends orders.
"""
import asyncio
import json
import random
import time
import urllib.request

import realtime_runtime as base

INFO_URL = 'https://api.hyperliquid.xyz/info'
REST_FALLBACK_SECONDS = 30
REST_INTERVAL_SECONDS = 1.0
WS_SILENCE_SECONDS = 5


def _rest_btc_mid():
    body = json.dumps({'type': 'allMids'}).encode('utf-8')
    request = urllib.request.Request(
        INFO_URL,
        data=body,
        headers={'Content-Type': 'application/json', 'User-Agent': 'BTC-FLOW-PAPER/1.0'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=6) as response:
        payload = json.loads(response.read().decode('utf-8'))
    price = float(payload['BTC'])
    if not 1000 < price < 1000000:
        raise ValueError('invalid REST BTC mid')
    return price


def _accept_rest_quote(quotes, price):
    now = time.time()
    ms = int(now * 1000)
    if ms <= quotes.highwater:
        ms = quotes.highwater + 1
    quotes.highwater = ms
    quotes.connected = True
    quotes.latest = {
        'ms': ms,
        'received_at': now,
        'price': price,
        'source': 'HYPERLIQUID_REST_ALL_MIDS',
    }


async def _rest_fallback(quotes, stop):
    end = time.monotonic() + REST_FALLBACK_SECONDS
    while not stop.is_set() and time.monotonic() < end:
        try:
            price = await asyncio.to_thread(_rest_btc_mid)
            _accept_rest_quote(quotes, price)
        except asyncio.CancelledError:
            raise
        except Exception:
            quotes.reconnects += 1
            quotes.disconnect()
        await asyncio.sleep(REST_INTERVAL_SECONDS)


async def stream(quotes, stop):
    """Prefer BBO WebSocket; automatically fall back to public REST on PC networks."""
    from websockets.asyncio.client import connect

    delay = 1
    while not stop.is_set():
        try:
            async with connect(
                base.WS_URL,
                open_timeout=10,
                ping_interval=20,
                ping_timeout=20,
                max_size=65536,
                max_queue=4,
            ) as ws:
                quotes.disconnect()
                quotes.connected = True
                await ws.send(json.dumps({'method': 'subscribe', 'subscription': {'type': 'bbo', 'coin': 'BTC'}}))
                last_valid = time.monotonic()
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2)
                    except asyncio.TimeoutError:
                        if time.monotonic() - last_valid >= WS_SILENCE_SECONDS:
                            raise TimeoutError('Hyperliquid BBO stream silent')
                        continue
                    if quotes.receive(json.loads(raw), time.time()):
                        quotes.latest['source'] = 'HYPERLIQUID_WS_BBO'
                        last_valid = time.monotonic()
                        delay = 1
        except asyncio.CancelledError:
            raise
        except Exception:
            quotes.reconnects += 1
        finally:
            quotes.disconnect()

        if stop.is_set():
            break

        await _rest_fallback(quotes, stop)
        if stop.is_set():
            break
        await asyncio.sleep(delay + random.random())
        delay = min(30, delay * 2)
