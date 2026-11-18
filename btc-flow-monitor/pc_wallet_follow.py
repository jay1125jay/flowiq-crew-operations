"""Apply public BTC fills locally on arrival; synchronize the same PAPER ledger in background."""
import asyncio
import copy
import datetime as dt
import json
import math
import itertools
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from websockets.asyncio.client import connect

REPO = 'https://github.com/jay1125jay/flowiq-crew-operations.git'
LEDGER = 'btc-flow-monitor/trader-discovery/wallet-paper.json'
ENGINE_VERSION = 'stream-20261118-2'


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True,
                          text=True, timeout=120).stdout.strip()


def verified(ledger):
    if ledger.get('paper_only') is not True or ledger.get('real_trading_enabled') is not False:
        raise ValueError('Expected PAPER ledger')
    return ledger


def apply_event(ledger, event, paper, applied_ms=None):
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
    executed = int(row.get('_paper_applied_ms', applied_ms if applied_ms is not None else received))
    at = dt.datetime.fromtimestamp(received/1000, dt.timezone.utc).isoformat()
    applied_at = dt.datetime.fromtimestamp(executed/1000, dt.timezone.utc).isoformat()
    previous_position = copy.deepcopy(updated.get('position'))
    closed_before = len(updated.get('closed', []))
    try:
        paper.apply_fill(updated, row, updated.get('source_equity_usd', 0),
                         allow_open=-2000 <= executed-ms <= paper.FRESH_FILL_MS)
    except ValueError:
        return 'recover'
    price = float(row['px'])
    paper.mark(updated, price, at)
    size = float(row['startPosition']) + (1 if row['side']=='B' else -1)*float(row['sz'])
    updated.update(source_size=size, source_btc_size=size, source_position_at=at,
                   last_at=at, price=price, fill_cursor=ms-1, error=None)
    updated['stream_keys'] = [key for key in updated.get('stream_keys', []) if key[0]==ms] + [[ms,tid]]
    timing = dict(source_at=dt.datetime.fromtimestamp(ms/1000, dt.timezone.utc).isoformat(),
                  received_at=at, applied_at=applied_at, receive_delay_ms=received-ms,
                  apply_delay_ms=executed-ms, processing_delay_ms=executed-received)
    updated['last_fill'].update(timing)
    position = updated.get('position')
    if position and (not previous_position or position['side'] != previous_position['side']):
        position.update(timing)
    for closed in updated.get('closed', [])[closed_before:]:
        closed.update(timing)
    peak = max(updated.get('peak_krw', paper.CAPITAL), updated['equity_krw'])
    updated['peak_krw'] = peak
    if peak:
        updated['max_drawdown_pct'] = max(updated.get('max_drawdown_pct',0),100*(1-updated['equity_krw']/peak))
    ledger['accounts'][address] = updated
    return 'applied'


def apply_ordered(ledger, batch, paper, applied_ms=None):
    """Preserve time order, but resolve tied fills using the source position chain."""
    done, statuses, blocked = [], {}, set()
    ordered = sorted(batch, key=lambda item: (item[1][0], int(item[1][1]['time'])))
    for (wallet, _), group in itertools.groupby(ordered, key=lambda item: (item[1][0], int(item[1][1]['time']))):
        if wallet in blocked:
            continue
        remaining = list(group)
        while remaining:
            progressed = False
            for item in remaining[:]:
                seq, event = item
                status = apply_event(ledger, event, paper, applied_ms)
                if status == 'recover':
                    continue
                statuses[seq] = status
                done.append(seq)
                remaining.remove(item)
                progressed = True
            if not progressed:
                blocked.add(wallet)
                break
    return done, statuses, blocked


def merge_recoveries(ledger, recoveries):
    from publish_wallet_paper import merge_observations
    for _, base, candidate in recoveries:
        ledger, _, _ = merge_observations(base, candidate, ledger)
    return ledger


def reconcile_wallet(root, base, address):
    # A separate checkout prevents REST recovery from holding the publish loop.
    with tempfile.TemporaryDirectory(prefix='cash-flow-recovery-') as directory:
        folder = Path(directory)
        data = folder/'trader-discovery'
        data.mkdir()
        shutil.copy2(root/'btc-flow-monitor/wallet_paper.py', folder/'wallet_paper.py')
        (data/'wallet-paper.json').write_text(json.dumps(base), encoding='utf-8')
        (data/'selected-whales.json').write_text(json.dumps(base['selected_whales']), encoding='utf-8')
        result = subprocess.run([sys.executable, '-u', str(folder/'wallet_paper.py'), '--wallet', address], timeout=240)
        if result.returncode not in (0, 2):
            result.check_returncode()
        return verified(json.loads((data/'wallet-paper.json').read_text(encoding='utf-8')))


def synchronize(root, batch, repair, paper, recoveries=()):
    git(root,'fetch','--depth=1','origin','main')
    git(root,'reset','--hard','origin/main')
    path = root/LEDGER
    ledger = verified(json.loads(path.read_text(encoding='utf-8')))
    original = copy.deepcopy(ledger)
    stamp = int(time.time()*1000)
    done, statuses, blocked = apply_ordered(ledger, batch, paper, stamp)
    ledger = merge_recoveries(ledger, recoveries)
    more, more_statuses, blocked = apply_ordered(ledger, batch, paper, stamp)
    done = list(set(done) | set(more))
    changed = ledger != original
    if changed:
        path.write_text(json.dumps(ledger,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if changed or repair:
        ledger['updated_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        ledger['pc_sync_at'] = ledger['updated_at']
        ledger['pc_engine_version'] = ENGINE_VERSION
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
        self.recovery_wake=asyncio.Event()
        self.recovery_due={address: 0 for address in self.ledger['accounts']}
        self.recovery_backoff={}
        self.recoveries=[]
        self.recovery_serial=0
        self.rest_cooldown=0
        self.blocked_wallets=set()
        self.recovery_retry_after={}
        self.last_received_ms=0
        db.execute('CREATE TABLE IF NOT EXISTS pending (seq INTEGER PRIMARY KEY, wallet TEXT, tid TEXT, payload TEXT, received INTEGER, UNIQUE(wallet,tid))')

    def pending(self):
        return [(seq,(wallet,json.loads(payload),ms)) for seq,wallet,payload,ms in
                self.db.execute('SELECT seq,wallet,payload,received FROM pending ORDER BY seq')]

    def receive(self,message):
        data=message.get('data')
        if message.get('channel')!='userFills' or not isinstance(data,dict):
            return
        wallet=data.get('user','').lower()
        if wallet not in self.ledger['accounts']:
            return
        ms=int(dt.datetime.now(dt.timezone.utc).timestamp()*1000)
        self.last_received_ms=ms
        fills=sorted((r for r in data.get('fills',[]) if r.get('coin')=='BTC'),key=lambda r:int(r['time']))
        with self.db:
            for row in fills:
                row = {key:value for key,value in row.items() if not key.startswith('_paper_')}
                self.db.execute('INSERT OR IGNORE INTO pending(wallet,tid,payload,received) VALUES(?,?,?,?)',
                                (wallet,str(row['tid']),json.dumps(row),ms))
        self.drain(wallet)
        if fills:
            self.wake.set()

    def drain(self, wallet=None):
        batch=[item for item in self.pending() if wallet is None or item[1][0]==wallet]
        applied_ms=int(dt.datetime.now(dt.timezone.utc).timestamp()*1000)
        working=copy.deepcopy(self.ledger)
        _, statuses, blocked=apply_ordered(working,batch,self.paper,applied_ms)
        reports=[]
        with self.db:
            for seq, (_,row,received) in batch:
                if statuses.get(seq)=='applied' and '_paper_applied_ms' not in row:
                    row['_paper_applied_ms']=applied_ms
                    self.db.execute('UPDATE pending SET payload=? WHERE seq=?',(json.dumps(row),seq))
                    reports.append((row['tid'],received-int(row['time']),applied_ms-int(row['time'])))
        # Commit execution timing before exposing the resulting local account.
        self.ledger=working
        for tid,receive_delay,apply_delay in reports:
            print('PAPER APPLIED',tid,'receive_ms',receive_delay,'apply_ms',apply_delay,flush=True)
        for address in blocked:
            # Wake immediately for a new gap; repeated events cannot bypass backoff.
            if address not in self.blocked_wallets:
                self.recovery_due[address]=max(time.monotonic(),self.recovery_retry_after.get(address,0))
        if wallet is None:
            self.blocked_wallets=blocked
        else:
            self.blocked_wallets.discard(wallet)
            self.blocked_wallets.update(blocked)
        if blocked:
            self.recovery_wake.set()

    async def recover(self):
        loop=asyncio.get_running_loop()
        while True:
            self.recovery_wake.clear()
            addresses=list(self.ledger['accounts'])
            for address in addresses:
                self.recovery_due.setdefault(address,0)
            due=min(addresses,key=lambda a:self.recovery_due[a])
            delay=max(self.rest_cooldown,self.recovery_due[due])-loop.time()
            if delay>0:
                try:
                    await asyncio.wait_for(self.recovery_wake.wait(),timeout=delay)
                except TimeoutError:
                    pass
                continue
            base=copy.deepcopy(self.ledger)
            try:
                candidate=await asyncio.to_thread(reconcile_wallet,self.root,base,due)
                error=candidate['accounts'][due].get('error')
                backoff=self.recovery_backoff.get(due,60)
                if error:
                    backoff=min(900,backoff*2)
                    self.recovery_due[due]=loop.time()+backoff
                    self.recovery_retry_after[due]=self.recovery_due[due]
                    if '429' in error:
                        self.rest_cooldown=loop.time()+backoff
                    print('RECOVERY WAIT',due[:10],backoff,error,flush=True)
                else:
                    backoff=60
                    self.recovery_due[due]=loop.time()+300
                    print('RECOVERY OK',due[:10],flush=True)
                self.recovery_backoff[due]=backoff
                self.rest_cooldown=max(self.rest_cooldown,loop.time()+15)
                self.recovery_serial+=1
                proposal=(self.recovery_serial,base,candidate)
                self.recoveries.append(proposal)
                self.ledger=merge_recoveries(self.ledger,[proposal])
                self.drain()
                if not error and due in self.blocked_wallets:
                    self.recovery_due[due]=loop.time()+15
                self.wake.set()
            except Exception as exc:
                self.recovery_due[due]=loop.time()+120
                print('RECOVERY ERROR',due[:10],str(exc),flush=True)
            # Recovery is rate limited independently of live event processing.
            await asyncio.sleep(2)

    async def publish(self):
        loop=asyncio.get_running_loop()
        next_check=0
        next_publish=0
        failures=0
        while True:
            # Socket reception continues while publishing/recovery is throttled.
            await asyncio.sleep(max(0,next_publish-loop.time()))
            self.wake.clear()
            repair=loop.time()>=next_check
            self.repair=False
            batch=self.pending()
            proposals=list(self.recoveries)
            try:
                ledger,done=await asyncio.to_thread(synchronize,self.root,batch,repair,self.paper,proposals)
                with self.db:
                    self.db.executemany('DELETE FROM pending WHERE seq=?',[(seq,) for seq in done])
                published={item[0] for item in proposals}
                self.recoveries=[item for item in self.recoveries if item[0] not in published]
                self.ledger=merge_recoveries(ledger,self.recoveries)
                self.drain()
                next_check=loop.time()+30
                failures=0
                next_publish=loop.time()+10
                print('PAPER SYNCED; pending:',len(self.pending()),'version:',ENGINE_VERSION,flush=True)
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
    observer.drain()
    print('ENGINE VERSION',ENGINE_VERSION,'PAPER ONLY',flush=True)
    await asyncio.gather(observer.listen(),observer.publish(),observer.recover())


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='btc-wallet-paper-') as directory:
        root=Path(directory)
        git(root,'clone','--depth=1','--filter=blob:none','--sparse',REPO,'.')
        git(root,'sparse-checkout','set','btc-flow-monitor')
        with sqlite3.connect(Path(__file__).with_name('pending-paper.sqlite3')) as db:
            asyncio.run(run(root,db))

