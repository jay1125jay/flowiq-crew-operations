#!/usr/bin/env python3
"""Forward-only, six independent PAPER accounts. No order API or credentials."""
import copy
import datetime as dt
import json
import math
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / 'data/adaptive-meta.json'
ENGINES = ('WHALE_COPY', 'SMART_MONEY', 'MARKET_STRUCTURE', 'DERIVATIVES', 'FIXED_ENSEMBLE', 'ADAPTIVE_META')
COMPONENTS = ENGINES[1:4]
START = 1000.0
NOTIONAL = 500.0
FEE = .0005
SLIP = .0003
ENTRY_THRESHOLD = .15
VERSION = 3


def stamp(s):
    x = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    if x.tzinfo is None:
        raise ValueError('timezone required')
    return x


def fresh(s, now, seconds=900):
    age = (stamp(now) - stamp(s)).total_seconds()
    if not 0 <= age <= seconds:
        raise ValueError('stale or future observation')


def safe(x):
    if x.get('paper_only') is not True or x.get('real_trading_enabled') is not False:
        raise ValueError('explicit PAPER-only flags required')


def number(x):
    v = float(x)
    if not math.isfinite(v):
        raise ValueError('nonfinite number')
    return v


def clamp(x, a=-1., b=1.):
    return max(a, min(b, x))


def direction(x):
    return 'LONG' if x > ENTRY_THRESHOLD else 'SHORT' if x < -ENTRY_THRESHOLD else 'WAIT'


def stats(closed):
    p = [number(t['pnl_usd']) for t in closed]
    wins = [x for x in p if x > 0]
    losses = [x for x in p if x < 0]
    return dict(n=len(p), expectancy=sum(p)/len(p) if p else 0., net=sum(p),
                pf=sum(wins)/abs(sum(losses)) if losses else None,
                pf_status='FINITE' if losses else 'NO_LOSSES' if wins else 'NO_TRADES',
                win_rate=100*len(wins)/len(p) if p else None,
                average_win=sum(wins)/len(wins) if wins else 0.,
                average_loss=sum(losses)/len(losses) if losses else 0.)


def reliability(a, regime='RANGE'):
    trades = a.get('closed', [])
    if len(trades) < 30:
        return .5
    def quality(rows):
        s = stats(rows)
        scale = max(1., abs(s['average_loss']), s['average_win'])
        return math.tanh(s['expectancy']/scale)
    local = [x for x in trades if x.get('regime') == regime]
    # Lifetime dominates. Recent/regime evidence gets additional shrinkage.
    q = .6*quality(trades) + .25*quality(trades[-30:])
    q += .15*len(local)/(len(local)+30)*quality(local)
    return clamp(.5 + .4*len(trades)/(len(trades)+60)*q, .2, .8)


def account():
    return dict(starting_equity_usd=START, cash=START, positions={}, closed=[],
                peak=START, mdd_pct=0., fees_usd=0., funding_usd=0., liquidations=0)


def migrate(state, now):
    if state.get('schema_version') == VERSION:
        safe(state)
        if set(state.get('accounts', {})) != set(ENGINES):
            raise ValueError('corrupt competition accounts')
        return state
    # Old signal-only records are NOT trades. Preserve them, start a new fair epoch.
    return dict(schema_version=VERSION, paper_only=True, real_trading_enabled=False,
                started_at=now, accounts={k: account() for k in ENGINES},
                legacy_snapshot=copy.deepcopy(state), whale_observed={}, history=[],
                engine_weights={k: 1/3 for k in COMPONENTS}, weight_sample_counts={})


def exit_value(p, price):
    sign = 1 if p['side'] == 'LONG' else -1
    px = price*(1-SLIP*sign)
    fee = px*p['qty']*FEE
    return (px-p['entry_price'])*p['qty']*sign-fee, px, fee


def equity(a, price):
    return a['cash'] + sum(exit_value(p, price)[0] for p in a['positions'].values())


def close(a, key, price, now, reason):
    p = a['positions'].pop(key)
    proceeds, px, fee = exit_value(p, price)
    a['cash'] += proceeds
    a['fees_usd'] += fee
    a['closed'].append(dict(source=key, side=p['side'], entry_at=p['entry_at'], exit_at=now,
        entry_price=p['entry_price'], exit_price=px, qty=p['qty'],
        entry_fee=p['entry_fee'], exit_fee=fee, funding_usd=p['funding_usd'],
        pnl_usd=proceeds-p['entry_fee']-p['funding_usd'], regime=p['regime'], reason=reason))


def open_position(a, key, side, price, now, regime, allocation=NOTIONAL):
    used = sum(p['notional_usd'] for p in a['positions'].values())
    # Same maximum exposure for all engines; no leverage in this comparison epoch.
    budget = min(allocation, max(0., min(NOTIONAL, equity(a, price)*.5)-used))
    if budget < 10:
        return
    px = price*(1+SLIP if side == 'LONG' else 1-SLIP)
    fee = budget*FEE
    a['cash'] -= fee
    a['fees_usd'] += fee
    a['positions'][key] = dict(side=side, entry_price=px, qty=budget/px,
        notional_usd=budget, entry_fee=fee, entry_at=now, regime=regime, funding_usd=0.)


def mark(a, price):
    eq = equity(a, price)
    a['peak'] = max(a['peak'], eq)
    a['mdd_pct'] = max(a['mdd_pct'], 100*(a['peak']-eq)/a['peak'])
    s = stats(a['closed'])
    a.update(equity_usd=eq, net_pnl_usd=eq-START, return_pct=100*(eq/START-1),
        unrealized_pnl_usd=sum(exit_value(p, price)[0]-p['entry_fee']-p['funding_usd'] for p in a['positions'].values()),
        closed_count=s['n'], expectancy_usd=s['expectancy'], profit_factor=s['pf'],
        profit_factor_status=s['pf_status'], win_rate_pct=s['win_rate'],
        average_win_usd=s['average_win'], average_loss_usd=s['average_loss'],
        return_drawdown_ratio=(100*(eq/START-1)/a['mdd_pct']) if a['mdd_pct'] else None,
        regime_performance={r: stats([t for t in a['closed'] if t['regime'] == r])
                            for r in sorted({t['regime'] for t in a['closed']})})


def market_structure(candles):
    if len(candles) < 24:
        return 0., 'WARMUP'
    c = candles[-24:]
    prices = [number(x['c']) for x in c]
    fast = statistics.mean(prices[-6:])
    slow = statistics.mean(prices)
    momentum = prices[-1]/prices[-7]-1
    returns = [prices[i]/prices[i-1]-1 for i in range(1, len(prices))]
    vol = statistics.pstdev(returns)
    trend = fast/slow-1
    regime = ('HIGH_VOL' if vol > .006 else 'LOW_VOL' if vol < .0002 else
              'TREND_UP' if trend > .002 else 'TREND_DOWN' if trend < -.002 else 'RANGE')
    prev = c[-7:-1]
    breakout = 1 if prices[-1] > max(number(x['h']) for x in prev) else -1 if prices[-1] < min(number(x['l']) for x in prev) else 0
    volume = number(c[-1]['v']) / max(1e-9, statistics.mean(number(x['v']) for x in prev))
    return clamp(60*trend + 35*momentum + .15*breakout*min(volume, 2)), regime


def cohort_score(coh, feed, now):
    values = []
    for w in coh.get('wallets', []):
        flags = w.get('category_flags', {})
        if not any(flags.values()):
            continue
        try:
            fresh(w['last_scanned_at'], now, 86400)
        except (ValueError, KeyError):
            continue
        side = feed['wallets'].get(w['address'])
        if side not in ('LONG', 'SHORT'):
            continue
        f = w.get('forward', {})
        quality = .5 + .5*math.tanh(number(f.get('net_pnl_usd', 0))/max(100., number(f.get('drawdown_usd', 0))))
        sample = min(1., number(f.get('closes', 0))/30)*min(1., number(f.get('days', 0))/30)
        weight = .5*(1-sample) + sample*quality
        values.append((1 if side == 'LONG' else -1, weight))
    return sum(s*w for s,w in values)/sum(w for _,w in values) if values else 0.


def derivatives(market, previous):
    funding = number(market['funding_rate'])
    oi = number(market['open_interest_btc'])
    old = previous.get('open_interest_btc')
    # Rising OI is NOT intrinsically bullish. Confirm with price direction.
    change = oi/old-1 if old and old > 0 else 0.
    move = number(market['reference_price'])/previous['reference_price']-1 if previous.get('reference_price') else 0.
    return clamp(-math.tanh(funding*5000)*.5 + math.tanh(change*50)*math.tanh(move*200)*.5)


def validate_inputs(coh, feed, market, rank, now):
    for obj, field in ((coh,'generated_at'), (feed,'generated_at'), (market,'generated_at'), (rank,'updated_at')):
        safe(obj)
        fresh(obj[field], now)
        if obj.get('errors'):
            raise ValueError('feed errors: refusing partial observations')
    if rank.get('status') != 'OK':
        raise ValueError('ranking unavailable')
    wallets = feed['wallets']
    if len(wallets) != feed['catalog_wallet_count'] or len(wallets) != feed['observed_wallet_count']:
        raise ValueError('incomplete positions')
    if set(wallets) != {w['address'] for w in coh['wallets']}:
        raise ValueError('catalog mismatch')
    if any(x not in ('LONG','SHORT','FLAT') for x in wallets.values()):
        raise ValueError('invalid wallet direction')
    price = number(feed['btc_mid_usd'])
    if not 1000 < price < 1000000:
        raise ValueError('invalid BTC price')
    if stamp(market['generated_at']) > stamp(feed['generated_at']):
        raise ValueError('market collected after execution observation')
    candles = market['candles']
    if len(candles) < 24:
        raise ValueError('insufficient closed candles')
    times = [int(x['T']) for x in candles]
    if times != sorted(set(times)) or any(b-a != 300000 for a,b in zip(times,times[1:])):
        raise ValueError('duplicate, unordered or missing candles')
    fresh(dt.datetime.fromtimestamp(times[-1]/1000,dt.timezone.utc).isoformat(), market['generated_at'], 600)
    for x in candles:
        o,h,l,c,v = (number(x[k]) for k in ('o','h','l','c','v'))
        if not 0 < l <= min(o,c) <= max(o,c) <= h or v < 0:
            raise ValueError('invalid candle')
    if number(market['open_interest_btc']) <= 0 or abs(number(market['funding_rate'])) > .05:
        raise ValueError('invalid derivatives')
    if abs(number(market['reference_price'])/price-1) > .05:
        raise ValueError('market/position price mismatch')
    return price


def advance(state, coh, feed, now, deriv=None, rank=None):
    market = deriv or {}
    rank = rank or {}
    price = validate_inputs(coh, feed, market, rank, now)
    observation = feed['generated_at']
    if state.get('last_observation_at'):
        if stamp(observation) == stamp(state['last_observation_at']):
            return state
        if stamp(observation) < stamp(state['last_observation_at']):
            raise ValueError('out-of-order observation')
    state = migrate(copy.deepcopy(state), observation)
    structure, regime = market_structure(market['candles'])
    smart = cohort_score(coh, feed, now)
    prior_market = state.get('previous_market', {})
    ds = derivatives(market, prior_market)
    raw = dict(SMART_MONEY=smart, MARKET_STRUCTURE=structure, DERIVATIVES=ds)
    raw['FIXED_ENSEMBLE'] = .4*smart+.4*structure+.2*ds
    # Freeze weights between new completed trades; step <= 0.01 per update.
    counts = {k: len(state['accounts'][k]['closed']) for k in COMPONENTS}
    if counts != state.get('weight_sample_counts'):
        desired = {k: reliability(state['accounts'][k], regime) for k in COMPONENTS}
        total = sum(desired.values())
        old = state['engine_weights']
        target = {k: desired[k]/total for k in COMPONENTS}
        distance = max(abs(target[k]-old[k]) for k in COMPONENTS)
        alpha = min(1., .01/distance) if distance else 1.
        state['engine_weights'] = {k: old[k]+alpha*(target[k]-old[k]) for k in COMPONENTS}
        state['weight_sample_counts'] = counts
    raw['ADAPTIVE_META'] = sum(raw[k]*state['engine_weights'][k] for k in COMPONENTS)
    # Original whale follower's baseline/change semantics, with common capital/risk.
    selected = [w['address'] for w in rank.get('ranked_wallets', [])
                if w.get('paper_candidate') or w.get('verified_whale')][:3]
    if any(w not in feed['wallets'] for w in selected):
        raise ValueError('control wallet missing from observation')
    whale_signals = [feed['wallets'][w] for w in selected]
    raw['WHALE_COPY'] = sum(1 if s == 'LONG' else -1 if s == 'SHORT' else 0 for s in whale_signals)/max(1,len(selected))
    decisions = {k: dict(score=v, signal=direction(v), confidence=abs(v)*100,
                        confidence_kind='SIGNAL_STRENGTH_NOT_WIN_PROBABILITY') for k,v in raw.items()}
    elapsed = (stamp(observation)-stamp(state.get('last_observation_at', observation))).total_seconds()/3600
    for k in ENGINES:
        a = state['accounts'][k]
        for p in a['positions'].values():
            # Explicit sampled estimate, not an exact exchange funding settlement.
            cost = p['qty']*price*number(prior_market.get('funding_rate', 0))*elapsed*(1 if p['side']=='LONG' else -1)
            p['funding_usd'] += cost
            a['cash'] -= cost
            a['funding_usd'] += cost
        mark(a, price)
        if equity(a, price) <= sum(p['qty']*price*.005 for p in a['positions'].values()) and a['positions']:
            for key in list(a['positions']):
                close(a, key, price, observation, 'SAMPLED_LIQUIDATION')
                a['liquidations'] += 1
            mark(a, price)
            continue
        if k == 'WHALE_COPY':
            for wallet in selected:
                side = feed['wallets'][wallet]
                before = state['whale_observed'].get(wallet)
                state['whale_observed'][wallet] = side
                if before is None or before == side:
                    continue
                if wallet in a['positions']:
                    close(a, wallet, price, observation, 'WHALE_DIRECTION_CHANGED')
                if side in ('LONG','SHORT') and len(a['positions']) < 3:
                    open_position(a, wallet, side, price, observation, regime, NOTIONAL/3)
        else:
            side = decisions[k]['signal']
            p = a['positions'].get('BTC')
            if p and p['side'] != side:
                close(a, 'BTC', price, observation, 'SIGNAL_CHANGE')
            if not a['positions'] and side in ('LONG','SHORT'):
                open_position(a, 'BTC', side, price, observation, regime)
        mark(a, price)
    state.update(updated_at=now, last_observation_at=observation, btc_mid_usd=price,
        regime=regime, decisions=decisions, previous_market={k:market[k] for k in ('funding_rate','open_interest_btc','reference_price')},
        paper_rules=dict(starting_equity_usd=START, max_notional_usd=NOTIONAL,
            max_equity_exposure=.5, leverage=1, fee_rate=FEE, slippage_rate=SLIP,
            funding_model='PREVIOUS_OBSERVED_HOURLY_RATE_ESTIMATE', entry_threshold=ENTRY_THRESHOLD),
        profitability='UNPROVEN', data_quality=dict(feed_errors=0, source_at=observation,
            unavailable=['market_wide_liquidations','market_wide_long_short_ratio']),
        control='Original whale-paper-state.json preserved. WHALE_COPY uses the same top-3 baseline/change rules with normalized common exposure.',
        limitations=['Sampled execution and liquidation; intrainterval moves are not observed.',
            'Funding uses the previous sampled hourly rate; gaps may misestimate funding.',
            'Confidence is signal strength, not calibrated probability. No profitability claim.'])
    state['history'] = (state.get('history', []) + [dict(at=observation, price=price, regime=regime)])[-288:]
    state['leaderboard'] = sorted([dict(engine=k, **{f:state['accounts'][k][f] for f in
        ('equity_usd','net_pnl_usd','profit_factor','mdd_pct','closed_count','expectancy_usd')}) for k in ENGINES],
        key=lambda x:x['net_pnl_usd'], reverse=True)
    return state


def main():
    def read(p):
        return json.loads((ROOT/p).read_text())
    state = read('data/adaptive-meta.json') if OUT.exists() else {}
    result = advance(state, read('trader-discovery/latest.json'), read('trader-discovery/current-positions.json'),
                     dt.datetime.now(dt.timezone.utc).isoformat(), read('data/adaptive-market.json'), read('data/whale-ranking.json'))
    tmp = OUT.with_suffix('.tmp')
    tmp.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    tmp.replace(OUT)
    print('ADAPTIVE PAPER PASS schema=3 accounts=6')

if __name__ == '__main__':
    main()
