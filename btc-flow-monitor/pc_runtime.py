#!/usr/bin/env python3
"""BTC FLOW PC entrypoint: Adaptive PAPER + separate six-category PAPER."""
import argparse
import asyncio

import category_realtime_runtime as category_runtime
import category_realtime_server
import category_top6_policy
import pc_price_stream
import pc_source_collector
import realtime_runtime as base_runtime


PC_SOURCE_TTL_SECONDS = 300
_ORIGINAL_CATEGORY_ADVANCE = category_runtime.category.advance


def _top6_category_advance(state, cohort, feed, now):
    ranked = category_top6_policy.apply_top6_policy(cohort)
    state = category_top6_policy.rotate_out_non_top6(state, ranked, feed, now, category_runtime.category)
    updated = _ORIGINAL_CATEGORY_ADVANCE(state, ranked, feed, now)
    updated['selection_policy'] = ranked.get('selection_policy')
    updated['selection_rankings'] = ranked.get('selection_rankings')
    return updated


async def run(args):
    # Windows/home PCs can need longer than CI to build a complete source bundle.
    # Keep true source timestamps intact, but allow a complete slow PC collection
    # cycle to remain eligible for PAPER evaluation.
    base_runtime.SOURCE_TTL = PC_SOURCE_TTL_SECONDS
    base_runtime.collect_sources = pc_source_collector.collect_sources
    # Some home/office networks allow Hyperliquid HTTPS while blocking/silencing
    # WebSocket traffic. Prefer WS BBO and automatically fall back to public REST.
    base_runtime.stream = pc_price_stream.stream
    # Track every fresh candidate but allow only the six best performers in each
    # category to reach the existing PAPER execution/accounting engine.
    category_runtime.category.advance = _top6_category_advance
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
