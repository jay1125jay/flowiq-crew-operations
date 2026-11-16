"""Forward-only BTC paper tracking, one independent KRW account per observed whale."""
import copy
import datetime as dt
import itertools
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
import pathlib
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / 'trader-discovery'
OUT = DATA / 'wallet-paper.json'
CAPITAL = 1_000_000
LEV = 10
FEE = .0005
SLIP = .0003
MAX_CLOCK_LEAD_SECONDS = 2.0
MAX_FOLLOW_GAP = 0.003
FRESH_FILL_MS = 15_000

def info(payload):
    req = urllib.request.Request('https://api.hyperliquid.xyz/info',
        data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)

def finite(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('non-finite fill data')
    return result


def fetch_fills(wallet, start, end):
    rows = info(dict(type='userFillsByTime', user=wallet, startTime=start,
                     endTime=end, aggregateByTime=False))
    if not isinstance(rows, list):
        raise ValueError('invalid fill response')
    if len(rows) >= 2000:
        if start >= end:
            raise ValueError('too many fills in one millisecond')
        middle = (start + end) // 2
        return fetch_fills(wallet, start, middle) + fetch_fills(wallet, middle + 1, end)
    return [r for r in rows if r['coin'] == 'BTC' and start <= int(r['time']) <= end]


def close_part(a, fraction, price, at, reason):
    pos = a['position']
    sign = pos['side']
    exit_price = price * (1 - sign * SLIP)
    cost = pos['notional'] * fraction
    entry_fee = pos['fee'] * fraction
    proceeds = cost * exit_price / pos['entry']
    before = a['cash']
    a['cash'] = max(0, before + sign * (proceeds-cost) - proceeds * FEE)
    a['closed'].append(dict(opened=pos['at'], closed=at, side=sign, entry=pos['entry'],
                            exit=exit_price, net_krw=a['cash']-before-entry_fee, reason=reason,
                            close_fraction=fraction, cash_after_krw=a['cash']))
    if fraction >= 1:
        a['position'] = None
    else:
        pos['notional'] -= cost
        pos['fee'] -= entry_fee


def mark(a, price, at):
    pos = a.get('position')
    unreal = 0
    if pos:
        move = pos['side'] * (price / pos['entry'] - 1)
        unreal = move * pos['notional']
        if a['cash'] + unreal <= .005 * pos['notional'] * price / pos['entry']:
            close_part(a, 1, price, at, 'liquidation')
            unreal = 0
    a['equity_krw'] = max(0, a['cash'] + unreal)


def apply_fill(a, row, source_equity, allow_open=True):
    price, size, before = map(finite, (row['px'], row['sz'], row['startPosition']))
    if min(price, size) <= 0 or row['side'] not in ('B','A'):
        raise ValueError('invalid fill price, size or side')
    sign = 1 if row['side'] == 'B' else -1
    at = dt.datetime.fromtimestamp(int(row['time'])/1000, dt.timezone.utc).isoformat()
    mark(a, price, at)
    reduction = min(size, abs(before)) if before * sign < 0 else 0
    pos = a.get('position')
    if reduction and pos and pos['side'] == -sign:
        close_part(a, reduction / abs(before), price, at, 'source_fill')
    opening = size - reduction
    pos = a.get('position')
    if allow_open and opening > 1e-12:
        if pos and pos['side'] != sign:
            raise ValueError('fill direction mismatch')
        mark(a, price, at)
        pos = a.get('position')
        used = pos['notional'] * price / pos['entry'] if pos else 0
        budget = a['equity_krw']
        nominal = max(0, budget*LEV-used)
        if pos:
            if source_equity <= 0:
                raise ValueError('invalid source equity for sizing')
            nominal = min(nominal, opening*price/source_equity*budget)
        if nominal > 0:
            entry = price*(1+sign*SLIP)
            fee = nominal*FEE
            a['cash'] -= fee
            if pos:
                qty = pos['notional']/pos['entry'] + nominal/entry
                pos['notional'] += nominal
                pos['entry'] = pos['notional']/qty
                pos['fee'] += fee
            else:
                a['position'] = dict(side=sign, entry=entry, notional=nominal, fee=fee, at=at)
    a['last_fill'] = dict(tid=row['tid'], at=at, price=price)
    a['fill_count'] += 1


def process_batch(a, rows, source_equity, end, price, stamp, observed_ms=None):
    if 'fill_cursor' not in a:
        # Preserve the old direction-only experiment, including its open positions.
        legacy = dict(a)
        a.clear()
        a.update(legacy_direction_account=legacy, cash=CAPITAL, closed=[], position=None,
                 equity_krw=CAPITAL, fill_cursor=end, fill_count=0, peak_krw=CAPITAL)
    seen = {tuple(key) for key in a.get('stream_keys', [])}
    pending = []
    for row in rows:
        key = (int(row['time']), int(row['tid']))
        if key not in seen and a['fill_cursor'] < key[0] <= end:
            seen.add(key)
            pending.append(row)
    pending.sort(key=lambda row: int(row['time']))
    for ms, group in itertools.groupby(pending, key=lambda row: int(row['time'])):
        remaining = list(group)
        while remaining:
            expected = a.get('source_size')
            index = next((i for i, row in enumerate(remaining)
                          if expected is None or math.isclose(finite(row['startPosition']), expected,
                                                              rel_tol=0, abs_tol=1e-8)), None)
            if index is None:
                raise ValueError('BTC fill history gap or order mismatch')
            row = remaining.pop(index)
            before = finite(row['startPosition'])
            apply_fill(a, row, source_equity, allow_open=observed_ms is None or observed_ms-ms <= FRESH_FILL_MS)
            a['source_size'] = before + (1 if row['side'] == 'B' else -1)*finite(row['sz'])
    mark(a, price, stamp)
    a.update(fill_cursor=end, last_at=stamp, price=price, error=None)
    a['stream_keys'] = [key for key in a.get('stream_keys', []) if key[0] > end]

def follow_snapshot(account, size, entry, bid, ask, quote):
    account.pop('follow_wait_gap_pct', None)
    if account['position'] or not size or account['cash'] <= 0:
        return
    side = 1 if size > 0 else -1
    execution = (ask if side > 0 else bid) * (1 + side * SLIP)
    gap = abs(execution - entry) / entry
    if gap > MAX_FOLLOW_GAP:
        account['follow_wait_gap_pct'] = 100 * gap
        return
    nominal = account['cash'] * LEV
    fee = nominal * FEE
    account['cash'] -= fee
    account['position'] = dict(side=side, entry=execution, notional=nominal, fee=fee,
                               at=quote.isoformat(), reason='snapshot_follow',
                               source_entry=entry, entry_gap_pct=100*gap)
    mark(account, (bid+ask)/2, quote.isoformat())


def now():
    return dt.datetime.now(dt.timezone.utc)


def main():
    ledger = json.loads(OUT.read_text()) if OUT.exists() else dict(paper_only=True,
        real_trading_enabled=False,initial_krw=CAPITAL,leverage=LEV,accounts={})
    assert ledger['paper_only'] is True and ledger['real_trading_enabled'] is False
    accounts = ledger['accounts']
    selected = json.loads((DATA/'selected-whales.json').read_text(encoding='utf-8'))
    addresses = [row['address'] for row in selected]
    if len(addresses) != 5 or len(set(addresses)) != 5:
        raise ValueError('Expected five distinct selected whale addresses')
    archived = ledger.setdefault('archived_accounts', {})
    for address in list(accounts):
        if address not in addresses:
            archived[address] = accounts.pop(address)
    for address in addresses:
        if address not in accounts:
            accounts[address] = archived.pop(address, dict(cash=CAPITAL,equity_krw=CAPITAL,position=None,closed=[]))
    ledger['selected_whales'] = selected
    started = now()
    def sample(address):
        try:
            stage = 'position'
            begin = time.monotonic()
            state = info(dict(type='clearinghouseState',user=address))
            source_equity = finite(state['marginSummary']['accountValue'])
            positions = state['assetPositions']
            btc = next((item['position'] for item in positions if item['position']['coin']=='BTC'), {})
            source_btc_size = finite(btc.get('szi', 0))
            source_entry = finite(btc['entryPx']) if source_btc_size else None
            if source_btc_size and source_entry <= 0:
                raise ValueError('invalid source entry')
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
            if not -MAX_CLOCK_LEAD_SECONDS <= age <= 15 or lag > 15 or elapsed > 15:
                raise ValueError(f'quote_age={age:.2f}s signal_gap={lag:.2f}s request_time={elapsed:.2f}s')
            # Align the cursor to the position snapshot, not to a later book.
            end = int(state['time'])
            quote_ms = int(book['time'])
            if abs(end-quote_ms) > FRESH_FILL_MS:
                raise ValueError('stale position snapshot')
            updated = copy.deepcopy(accounts[address])
            stage = 'fills'
            cursor = updated.get('fill_cursor')
            if cursor is not None and (cursor > end or any(key[0] > end for key in updated.get('stream_keys', []))):
                raise ValueError('old quote')
            try:
                rows = fetch_fills(address, cursor + 1, end) if cursor is not None and cursor < end else []
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or updated.get('position') or not source_btc_size:
                    raise
                rows = []
                updated['history_gap_at'] = quote.isoformat()
                updated['history_gap_reason'] = 'fill query rate limited; resumed from position snapshot'
            try:
                process_batch(updated, rows, source_equity, end, (bid+ask)/2, quote.isoformat(), quote_ms)
            except ValueError as exc:
                if str(exc) != 'BTC fill history gap or order mismatch':
                    raise
                updated = copy.deepcopy(accounts[address])
                pos = updated.get('position')
                if pos:
                    # Retry recent gaps so late fills can arrive before using a snapshot.
                    if end - cursor < 300_000:
                        raise
                    prior = finite(updated['source_size'])
                    if not prior or prior * pos['side'] <= 0:
                        raise
                    retained = max(0.0, min(1.0, source_btc_size / prior))
                    if retained < 1:
                        exit_quote = bid if pos['side'] > 0 else ask
                        close_part(updated, 1-retained, exit_quote, quote.isoformat(), 'snapshot_gap_recovery')
                updated['history_gap_at'] = quote.isoformat()
                updated['history_gap_reason'] = 'Missing source fills; reconciled at observed quote'
                updated['history_gap_start_ms'] = cursor
                process_batch(updated, [], source_equity, end, (bid+ask)/2, quote.isoformat(), quote_ms)
            if now().timestamp()*1000 - quote_ms > FRESH_FILL_MS:
                raise ValueError('stale quote after fill lookup')
            follow_snapshot(updated, source_btc_size, source_entry, bid, ask, quote)
            updated['source_size'] = source_btc_size
            updated['source_entry_px'] = source_entry
            updated['source_equity_usd'] = source_equity
            updated['source_btc_size'] = source_btc_size
            updated['source_position_at'] = received.isoformat()
            return updated,quote.isoformat(),received.isoformat(),None
        except (OSError,ValueError,KeyError,IndexError,TypeError) as exc:
            return None,None,None,f'{stage}: {type(exc).__name__}: {exc}'[:200]
    successes = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for a, result in zip(accounts.values(),pool.map(sample,accounts)):
            updated,stamp,received,error = result
            a['attempts'] = a.get('attempts',0)+1
            if error is not None or stamp <= a.get('last_at',''):
                a['error'] = error or 'old quote'
                a['misses'] = a.get('misses',0)+1
                continue
            updated['attempts'] = updated.get('attempts',0)+1
            a.clear()
            a.update(updated)
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

