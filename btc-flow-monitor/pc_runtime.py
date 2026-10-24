#!/usr/bin/env python3
"""BTC FLOW PC entrypoint: Adaptive PAPER + separate six-category PAPER."""
import argparse
import asyncio

import category_realtime_runtime as category_runtime
import category_realtime_server
import pc_price_stream
import pc_source_collector
import realtime_runtime as base_runtime


PC_SOURCE_TTL_SECONDS = 300


async def run(args):
    # Windows/home PCs can need longer than CI to build a complete source bundle.
    # Keep true source timestamps intact, but allow a complete slow PC collection
    # cycle to remain eligible for PAPER evaluation.
    base_runtime.SOURCE_TTL = PC_SOURCE_TTL_SECONDS
    base_runtime.collect_sources = pc_source_collector.collect_sources
    # Some home/office networks allow Hyperliquid HTTPS while blocking/silencing
    # WebSocket traffic. Prefer WS BBO and automatically fall back to public REST.
    base_runtime.stream = pc_price_stream.stream
    category_realtime_server.install()
    await category_runtime.run(args)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--state-dir',required=True)
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8080)
    parser.add_argument('--share-phone',action='store_true')
    parser.add_argument('--open-browser',action='store_true')
    parser.add_argument('--seconds',type=int,default=0)
    asyncio.run(run(parser.parse_args()))


if __name__=='__main__':
    main()
