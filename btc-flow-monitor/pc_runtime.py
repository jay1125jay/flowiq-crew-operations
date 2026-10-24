#!/usr/bin/env python3
"""BTC FLOW PC entrypoint: Adaptive PAPER + separate six-category PAPER."""
import argparse
import asyncio

import category_realtime_runtime as category_runtime
import category_realtime_server


async def run(args):
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
