"""Wake the original PAPER observer on public BTC fills. No exchange credentials."""
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from websockets.asyncio.client import connect

REPO = 'https://github.com/jay1125jay/flowiq-crew-operations.git'
LEDGER = 'btc-flow-monitor/trader-discovery/wallet-paper.json'


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True, timeout=120).stdout.strip()


def observe(root):
    # This checkout is created solely for this process. Discard a conflicting
    # unpublished sample and collect fresh data from the canonical balance.
    for _ in range(3):
        git(root, 'fetch', '--depth=1', 'origin', 'main')
        git(root, 'reset', '--hard', 'origin/main')
        runner = root/'btc-flow-monitor/wallet_paper.py'
        subprocess.run([sys.executable,str(runner)],check=True,timeout=240)
        git(root,'add','--',LEDGER)
        git(root,'-c','user.name=BTC FLOW PAPER','-c','user.email=btc-flow@users.noreply.github.com','commit','-m','data: PC whale PAPER observation')
        try:
            git(root,'push','origin','HEAD:main')
            return sorted(json.loads((root/LEDGER).read_text())['accounts'])
        except subprocess.CalledProcessError as exc:
            if not any(x in exc.stderr for x in ('fetch first','non-fast-forward','remote contains work')):
                raise
    raise RuntimeError('Concurrent writer; retry with fresh ledger')


def btc_event(message, addresses):
    data=message.get('data')
    return (message.get('channel')=='userFills' and isinstance(data,dict)
            and not data.get('isSnapshot') and data.get('user','').lower() in addresses
            and any(row.get('coin')=='BTC' for row in data.get('fills',[])))


async def listen(addresses, wake):
    while True:
        try:
            async with connect('wss://api.hyperliquid.xyz/ws',open_timeout=10) as ws:
                for wallet in addresses:
                    await ws.send(json.dumps({'method':'subscribe','subscription':{'type':'userFills','user':wallet}}))
                async for message in ws:
                    if btc_event(json.loads(message), addresses):
                        wake.set()
        except Exception as exc:
            print('Feed reconnect:',type(exc).__name__,flush=True)
            await asyncio.sleep(3)


async def run(root):
    wake=asyncio.Event()
    listener=None
    watched=[]
    try:
        while True:
            wake.clear()
            accounts=await asyncio.to_thread(observe,root)
            # Exchange user subscription cap. Every account is still polled.
            if accounts[:10]!=watched:
                if listener:
                    listener.cancel()
                    await asyncio.gather(listener,return_exceptions=True)
                watched=accounts[:10]
                listener=asyncio.create_task(listen(watched,wake))
            print('PAPER saved:',len(accounts),'wallets; streaming:',len(watched),flush=True)
            try:
                await asyncio.wait_for(wake.wait(),timeout=60)
            except TimeoutError:
                pass
    finally:
        if listener:
            listener.cancel()
            await asyncio.gather(listener,return_exceptions=True)


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='btc-wallet-paper-') as directory:
        root=Path(directory)
        git(root,'clone','--depth=1','--filter=blob:none','--sparse',REPO,'.')
        git(root,'sparse-checkout','set','btc-flow-monitor')
        asyncio.run(run(root))
