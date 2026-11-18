"""Apply public BTC fills locally on arrival; synchronize the same PAPER ledger in background."""
import asyncio
import copy
import datetime as dt
import json
import math
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from websockets.asyncio.client import connect

REPO = 'https://github.com/jay1125jay/flowiq-crew-operations.git'
LEDGER = 'btc-flow-monitor/trader-discovery/wallet-paper.json'


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True,
                          text=True, timeout=120).stdout.strip()


def verified(ledger):
    if ledger.get('paper_only') is not True or ledger.get('real_trading_enabled') is not False:
        raise ValueError('Expected PAPER ledger')
    return ledger


def apply_event(ledger, event, paper):
    address, row, received = event
    account = ledger['accounts'].get(address)
    if account is None:
        return 'retired'
    ms, tid = int(row['time']), int(row['tid'])
    if 'fill_cursor' not in account:
        return 'recover'
    if ms <= account['fill_cursor'] or [ms, tid] in account.get('stream_keys', []):
        return 'covered'
    if 'source_size' not in account or not math.isclose(float(row['startPosition']), account['source_size'], rel_tol=0, abs_tol=1e-8):
        return 'recover'
    updated = copy.deepcopy(account)
    at = dt.datetime.fromtimestamp(received/1000, dt.timezone.utc).isoformat()
    try:
        paper.apply_fill(updated, row, updated.get('source_equity_usd', 0),
                         allow_open=-2000 <= received-ms <= paper.FRESH_FILL_MS)
    except ValueError:
        return 'recover'
    price = float(row['px'])
    paper.mark(updated, price, at)
    size = float(row['startPosition']) + (1 if row['side']=='B' else -1)*float(row['sz'])
    updated.update(source_size=size, source_btc_size=size, source_position_at=at,
                   last_at=at, price=price, fill_cursor=ms-1, error=None)
    updated['stream_keys'] = [key for key in updated.get('stream_keys', []) if key[0]==ms] + [[ms,tid]]
    updated['last_fill'].update(received_at=at, receive_delay_ms=received-ms)
    peak = max(updated.get('peak_krw', paper.CAPITAL), updated['equity_krw'])
    updated['peak_krw'] = peak
    if peak:
        updated['max_drawdown_pct'] = max(updated.get('max_drawdown_pct',0),100*(1-updated['equity_krw']/peak))
    ledger['accounts'][address] = updated
    return 'applied'


def synchronize(root, batch, repair, paper):
    git(root,'fetch','--depth=1','origin','main')
    git(root,'reset','--hard','origin/main')
    path = root/LEDGER
    ledger = verified(json.loads(path.read_text(encoding='utf-8')))
    done, blocked = [], set()
    changed = False
    for seq,event in batch:
        if event[0] in blocked:
            continue
        status = apply_event(ledger,event,paper)
        if status=='recover':
            blocked.add(event[0])
            continue
        done.append(seq)
        changed |= status=='applied'
    if changed:
        path.write_text(json.dumps(ledger,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if repair:
        result = subprocess.run([sys.executable,str(root/'btc-flow-monitor/wallet_paper.py')],timeout=240)
        if result.returncode not in (0,2):
            result.check_returncode()
        ledger = verified(json.loads(path.read_text(encoding='utf-8')))
    if changed or repair:
        ledger['updated_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        ledger['pc_sync_at'] = ledger['updated_at']
        path.write_text(json.dumps(ledger,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    git(root,'add','--',LEDGER)
    if git(root,'diff','--cached','--name-only'):
        git(root,'-c','user.name=Cash Flow PAPER','-c','user.email=btc-flow@users.noreply.github.com',
            'commit','-m','data: synchronize PC PAPER fills')
        git(root,'push','origin','HEAD:main')
    return ledger,done


class Observer:
    def __init__(self,root,paper,db):
        self.root,self.paper,self.db=root,paper,db
        self.ledger=verified(json.loads((root/LEDGER).read_text(encoding='utf-8')))
        self.repair=True
        self.wake=asyncio.Event()
        db.execute('CREATE TABLE IF NOT EXISTS pending (seq INTEGER PRIMARY KEY, wallet TEXT, tid TEXT, payload TEXT, received INTEGER, UNIQUE(wallet,tid))')

    def pending(self):
        return [(seq,(wallet,json.loads(payload),ms)) for seq,wallet,payload,ms in
                self.db.execute('SELECT seq,wallet,payload,received FROM pending ORDER BY seq')]

    def receive(self,message):
        data=message.get('data')
        if message.get('channel')!='userFills' or not isinstance(data,dict) or data.get('isSnapshot'):
            return
        wallet=data.get('user','').lower()
        if wallet not in self.ledger['accounts']:
            return
        ms=int(dt.datetime.now(dt.timezone.utc).timestamp()*1000)
        fills=sorted((r for r in data.get('fills',[]) if r.get('coin')=='BTC'),key=lambda r:int(r['time']))
        with self.db:
            for row in fills:
                inserted=self.db.execute('INSERT OR IGNORE INTO pending(wallet,tid,payload,received) VALUES(?,?,?,?)',
                                         (wallet,str(row['tid']),json.dumps(row),ms)).rowcount
                if inserted:
                    status=apply_event(self.ledger,(wallet,row,ms),self.paper)
                    print('PAPER fill',wallet[:10],row['tid'],status,'delay_ms',ms-int(row['time']),flush=True)
        if fills:
            self.wake.set()

    async def publish(self):
        loop=asyncio.get_running_loop()
        next_check=0
        next_publish=0
        failures=0
        rate_backoff=60
        while True:
            # Socket reception continues while publishing/recovery is throttled.
            await asyncio.sleep(max(0,next_publish-loop.time()))
            self.wake.clear()
            repair=loop.time()>=next_check
            self.repair=False
            batch=self.pending()
            try:
                ledger,done=await asyncio.to_thread(synchronize,self.root,batch,repair,self.paper)
                with self.db:
                    self.db.executemany('DELETE FROM pending WHERE seq=?',[(seq,) for seq in done])
                self.ledger=ledger
                for _,event in self.pending():
                    apply_event(ledger,event,self.paper)
                if repair:
                    limited=any('429' in str(a.get('error','')) for a in ledger['accounts'].values())
                    rate_backoff=min(900,rate_backoff*2) if limited else 60
                    next_check=loop.time()+rate_backoff
                    if limited:
                        print('HTTP 429: REST cooldown',rate_backoff,'seconds; stream remains active',flush=True)
                failures=0
                next_publish=loop.time()+10
                print('PAPER saved; pending:',len(self.pending()),'next check in:',
                      max(0,int(next_check-loop.time())),'seconds',flush=True)
            except Exception as exc:
                failures+=1
                delay=min(120,5*2**min(failures,5))
                detail=getattr(exc,'stderr',None) or str(exc)
                print('PAPER sync failed; retry in',delay,'seconds:',str(detail)[-1000:],flush=True)
                if repair:
                    next_check=loop.time()+max(60,delay)
                next_publish=loop.time()+delay
                continue
            if self.pending() or self.repair:
                continue
            try:
                await asyncio.wait_for(self.wake.wait(),timeout=max(.1,next_check-loop.time()))
            except TimeoutError:
                pass

    async def listen(self):
        while True:
            try:
                async with connect('wss://api.hyperliquid.xyz/ws',open_timeout=10) as ws:
                    addresses=set(self.ledger['accounts'])
                    self.repair=True
                    self.wake.set()
                    for wallet in addresses:
                        await ws.send(json.dumps({'method':'subscribe','subscription':{'type':'userFills','user':wallet}}))
                    print('PAPER direct stream:',len(addresses),'wallets',flush=True)
                    while addresses==set(self.ledger['accounts']):
                        try:
                            message=await asyncio.wait_for(ws.recv(),timeout=25)
                        except TimeoutError:
                            await ws.send('{"method":"ping"}')
                            continue
                        self.receive(json.loads(message))
            except Exception as exc:
                print('Feed reconnect:',exc,flush=True)
                await asyncio.sleep(3)


async def run(root,db):
    sys.path.insert(0,str(root/'btc-flow-monitor'))
    import wallet_paper
    observer=Observer(root,wallet_paper,db)
    await asyncio.gather(observer.listen(),observer.publish())


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='btc-wallet-paper-') as directory:
        root=Path(directory)
        git(root,'clone','--depth=1','--filter=blob:none','--sparse',REPO,'.')
        git(root,'sparse-checkout','set','btc-flow-monitor')
        with sqlite3.connect(Path(__file__).with_name('pending-paper.sqlite3')) as db:
            asyncio.run(run(root,db))

