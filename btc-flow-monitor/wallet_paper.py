"""Forward-only BTC paper tracking, one independent KRW account per observed whale."""
import datetime as dt
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / 'trader-discovery'
OUT = DATA / 'wallet-paper.json'
CAPITAL = 1_000_000
LEV = 10
FEE = .0005
SLIP = .0003

def info(payload):
    req = urllib.request.Request('https://api.hyperliquid.xyz/info',
        data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)

def direction(state):
    positions = state['assetPositions']
    if not isinstance(positions, list):
        raise ValueError('invalid positions')
    for asset in positions:
        position = asset['position']
        if position['coin'] == 'BTC':
            size = float(position['szi'])
            if not math.isfinite(size):
                raise ValueError('invalid size')
            return (size > 0) - (size < 0)
    return 0

def advance(a, side, price, at):
    if a.get('last_at', '') >= at:
        return
    pos = a.get('position')
    blocked = a.get('blocked_side')
    if side != blocked:
        a.pop('blocked_side', None)
    if pos:
        sign = pos['side']
        move = sign * (price / pos['entry'] - 1)
        liquidated = move <= -(1 / LEV - .005)
        if side != sign or liquidated:
            exit_price = price * (1 - sign * SLIP)
            gross = sign * (exit_price / pos['entry'] - 1) * pos['notional']
            exit_fee = pos['notional'] * exit_price / pos['entry'] * FEE
            before = a['cash']
            a['cash'] = max(0, before + gross - exit_fee)
            a['closed'].append(dict(opened=pos['at'], closed=at, side=sign,
                entry=pos['entry'], exit=exit_price, net_krw=a['cash']-before-pos['fee'],
                reason='liquidation' if liquidated else 'source_change'))
            a['position'] = None
            if liquidated and side == sign:
                a['blocked_side'] = side
    if side and not a.get('position') and a.get('blocked_side') != side and a['cash'] > 0:
        nominal = min(CAPITAL, a['cash']) * LEV
        fee = nominal * FEE
        a['cash'] -= fee
        a['position'] = dict(side=side, entry=price*(1+side*SLIP), notional=nominal, fee=fee, at=at)
    pos = a.get('position')
    unreal = pos['side']*(price/pos['entry']-1)*pos['notional'] if pos else 0
    a.update(equity_krw=max(0,a['cash']+unreal), last_at=at, price=price, error=None)

def now():
    return dt.datetime.now(dt.timezone.utc)


def main():
    ledger = json.loads(OUT.read_text()) if OUT.exists() else dict(paper_only=True,
        real_trading_enabled=False,initial_krw=CAPITAL,leverage=LEV,accounts={})
    assert ledger['paper_only'] is True and ledger['real_trading_enabled'] is False
    accounts = ledger['accounts']
    catalog = json.loads((DATA/'latest.json').read_text())
    addresses = {r['address'].lower() for r in catalog['wallets'] if r['category_flags'].get('WHALE')}
    for path in (DATA/'research').glob('*public-profit-screen.json'):
        research = json.loads(path.read_text())
        addresses.update(r['address'].lower() for r in research['results'] if r.get('whale_history_pass'))
    for address in sorted(addresses):
        accounts.setdefault(address, dict(cash=CAPITAL,equity_krw=CAPITAL,position=None,closed=[]))
    started = now()
    def sample(address):
        try:
            stage = 'position'
            begin = time.monotonic()
            state = info(dict(type='clearinghouseState',user=address))
            side = direction(state)
            received = now()
            stage = 'quote'
            book = info(dict(type='l2Book',coin='BTC'))
            bid, ask = (float(rows[0]['px']) for rows in book['levels'])
            quote = dt.datetime.fromtimestamp(book['time']/1000,dt.timezone.utc)
            age = (now()-quote).total_seconds()
            lag = abs((received-quote).total_seconds())
            elapsed = time.monotonic()-begin
            if book['coin'] != 'BTC' or not 0 < bid <= ask <= bid*1.005:
                raise ValueError('invalid BTC book')
            if not 0 <= age <= 15 or lag > 15 or elapsed > 15:
                raise ValueError(f'quote_age={age:.2f}s signal_gap={lag:.2f}s request_time={elapsed:.2f}s')
            return side,(bid+ask)/2,quote.isoformat(),received.isoformat(),None
        except (OSError,ValueError,KeyError,IndexError,TypeError) as exc:
            return None,None,None,None,f'{stage}: {type(exc).__name__}: {exc}'[:200]
    successes = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for a, result in zip(accounts.values(),pool.map(sample,accounts)):
            side,price,stamp,received,error = result
            a['attempts'] = a.get('attempts',0)+1
            if error is not None or stamp <= a.get('last_at',''):
                a['error'] = error or 'old quote'
                a['misses'] = a.get('misses',0)+1
                continue
            advance(a,side,price,stamp)
            a['signal_received_at'] = received
            peak = max(a.get('peak_krw',CAPITAL),a['equity_krw'])
            a['peak_krw'] = peak
            a['max_drawdown_pct'] = max(a.get('max_drawdown_pct',0),100*(1-a['equity_krw']/peak))
            successes += 1
    ended = now()
    ledger['updated_at']=ended.isoformat()
    ledger['observed_count']=successes
    cycles=ledger.setdefault('cycles',[])
    cycles.append(dict(start=started.isoformat(),end=ended.isoformat(),ok=successes,total=len(accounts)))
    cutoff=(ended-dt.timedelta(days=1)).isoformat()
    ledger['cycles']=[c for c in cycles if c['end']>=cutoff]
    temp=OUT.with_suffix('.tmp')
    temp.write_text(json.dumps(ledger,indent=2,allow_nan=False)+'\n')
    temp.replace(OUT)
    print('observed',successes,'accounts',len(accounts))
    for address, account in accounts.items():
        if account.get('error'):
            print('OBSERVATION_MISSED',address[:10],account['error'],flush=True)
    if not successes:
        raise SystemExit(2)

if __name__=='__main__':
    main()
