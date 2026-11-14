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
REST_INTERVAL_SECONDS = 1.0
WS_SILENCE_SECONDS = 5


def _rest_book():
    body = json.dumps({'type': 'l2Book', 'coin': 'BTC'}).encode('utf-8')
    request = urllib.request.Request(
        INFO_URL,
        data=body,
        headers={'Content-Type': 'application/json', 'User-Agent': 'BTC-FLOW-PAPER/1.0'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=6) as response:
        payload = json.loads(response.read().decode('utf-8'))
    bids, asks = payload['levels']
    return {'channel': 'bbo', 'data': {
        'coin': payload['coin'], 'time': payload['time'], 'bbo': [bids[0], asks[0]],
    }}


def _publish(quotes, message, source):
    if not quotes.receive(message, time.time()):
        return False
    quotes.latest['source'] = source
    quotes.connected = True
    return True


async def _rest_fallback(quotes, stop):
    while not stop.is_set():
        latest = quotes.latest
        if not latest or latest.get('source') != 'HYPERLIQUID_WS_BBO' or (
            time.time() - latest['ms'] / 1000 >= REST_INTERVAL_SECONDS * 2
        ):
            try:
                book = await asyncio.to_thread(_rest_book)
                _publish(quotes, book, 'HYPERLIQUID_REST_L2_BOOK')
            except (OSError, ValueError, KeyError, IndexError, TypeError):
                pass  # The normal quote TTL expires the last verified price.
        await asyncio.sleep(REST_INTERVAL_SECONDS)


async def _websocket_stream(quotes, stop):
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
                await ws.send(json.dumps({'method': 'subscribe', 'subscription': {'type': 'bbo', 'coin': 'BTC'}}))
                last_valid = time.monotonic()
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2)
                    except asyncio.TimeoutError:
                        if time.monotonic() - last_valid >= WS_SILENCE_SECONDS:
                            raise TimeoutError('Hyperliquid BBO stream silent')
                        continue
                    if _publish(quotes, json.loads(raw), 'HYPERLIQUID_WS_BBO'):
                        last_valid = time.monotonic()
                        delay = 1
        except asyncio.CancelledError:
            raise
        except Exception:
            quotes.reconnects += 1

        if stop.is_set():
            break

        await asyncio.sleep(delay + random.random())
        delay = min(30, delay * 2)

async def stream(quotes, stop):
    tasks = [asyncio.create_task(worker(quotes, stop))
             for worker in (_rest_fallback, _websocket_stream)]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        quotes.disconnect()
