#!/usr/bin/env python3
"""Rank every classified BTC trader and keep the best six per PAPER category.

Selection only. Existing PAPER accounting/execution logic stays unchanged.
"""
import copy
import math

CATS = ('WHALE', 'HIGH_WIN_RATE', 'HIGH_PROFIT', 'CONSISTENT', 'SCALPER', 'SWING')
TOP_N = 6


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, value))


def _log_score(value, scale=5.0):
    value = max(0.0, _num(value))
    if value <= 0:
        return 0.0
    return _clip(math.log10(1.0 + value) / scale * 100.0)


def _base_parts(row):
    hist = row.get('history') or {}
    fwd = row.get('forward') or {}
    hold = row.get('holding') or {}
    win = _clip(_num(hist.get('win_rate_pct')))
    pf = _clip(_num(hist.get('profit_factor')) / 3.0 * 100.0)
    closes = _clip(_num(hist.get('closes')) / 200.0 * 100.0)
    pnl = _log_score(hist.get('net_pnl_usd'))
    notional = _clip(_num(hist.get('avg_fill_notional_usd')) / 100000.0 * 100.0)
    fwd_closes = _num(fwd.get('closes'))
    fwd_net = _num(fwd.get('stress_net_pnl_usd', fwd.get('net_pnl_usd')))
    fwd_dd = max(0.0, _num(fwd.get('drawdown_usd')))
    fwd_quality = 0.0
    if fwd_closes > 0:
        ratio = max(0.0, fwd_net) / (max(0.0, fwd_net) + fwd_dd + 100.0)
        fwd_quality = _clip(100.0 * ratio)
    short_share = _clip(_num(hold.get('within_1h_share')) * 100.0)
    long_share = _clip(_num(hold.get('at_least_1h_share')) * 100.0)
    episodes = _clip(_num(hold.get('complete_episodes')) / 20.0 * 100.0)
    return {
        'win': win, 'pf': pf, 'closes': closes, 'pnl': pnl, 'notional': notional,
        'fwd': fwd_quality, 'short_share': short_share, 'long_share': long_share,
        'episodes': episodes,
    }


def score_wallet(row, category):
    p = _base_parts(row)
    if category == 'WHALE':
        score = .30*p['notional'] + .25*p['pf'] + .20*p['win'] + .15*p['pnl'] + .10*p['closes']
    elif category == 'HIGH_WIN_RATE':
        score = .50*p['win'] + .20*p['pf'] + .15*p['closes'] + .15*p['pnl']
    elif category == 'HIGH_PROFIT':
        score = .40*p['pnl'] + .25*p['pf'] + .20*p['win'] + .15*p['closes']
    elif category == 'CONSISTENT':
        score = .35*p['fwd'] + .25*p['pf'] + .20*p['win'] + .20*p['closes']
    elif category == 'SCALPER':
        score = .35*p['short_share'] + .20*p['episodes'] + .20*p['win'] + .15*p['pf'] + .10*p['pnl']
    elif category == 'SWING':
        score = .35*p['long_share'] + .20*p['episodes'] + .20*p['pf'] + .15*p['pnl'] + .10*p['win']
    else:
        score = .30*p['win'] + .25*p['pf'] + .20*p['pnl'] + .15*p['closes'] + .10*p['fwd']

    if row.get('verified'):
        score += 10.0
    elif row.get('forward_mature'):
        score += 5.0
    return round(score, 3)


def observed_net_profit(row):
    try:
        value = float((row.get('history') or {}).get('net_pnl_usd'))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def apply_top6_policy(cohort):
    """Return a copied cohort where each category flag is true only for its TOP 6."""
    out = copy.deepcopy(cohort)
    rows = out.get('wallets', [])
    rankings = {}

    for cat in CATS:
        eligible = [r for r in rows if (r.get('category_flags') or {}).get(cat) and r.get('address')]
        ranked = sorted(
            eligible,
            key=lambda r: (score_wallet(r, cat), str(r.get('address'))),
            reverse=True,
        )
        if cat == 'WHALE':
            # Stable sort retains the performance score as a tie-breaker.
            ranked = [row for row in ranked if observed_net_profit(row) is not None]
            ranked.sort(key=observed_net_profit, reverse=True)
        selected = ranked[:TOP_N]
        selected_addresses = {r['address'] for r in selected}
        rankings[cat] = [
            {
                'rank': i + 1,
                **({'observed_net_profit_usd': observed_net_profit(r)} if cat == 'WHALE' else {}),
                'address': r['address'],
                'score': score_wallet(r, cat),
                'verified': bool(r.get('verified')),
                'forward_mature': bool(r.get('forward_mature')),
            }
            for i, r in enumerate(ranked)
        ]

        for row in rows:
            flags = row.setdefault('category_flags', {})
            if flags.get(cat):
                row.setdefault('selection_scores', {})[cat] = score_wallet(row, cat)
                row.setdefault('selected_top6', {})[cat] = row.get('address') in selected_addresses
                if row.get('address') not in selected_addresses:
                    flags[cat] = False

    for row in rows:
        row['categories'] = [cat for cat in CATS if (row.get('category_flags') or {}).get(cat)]

    out['selection_policy'] = {
        'mode': 'ALL_FRESH_CANDIDATES_TRACKED_TOP6_BY_PERFORMANCE_SCORE',
        'top_n_per_category': TOP_N,
        'candidate_catalog_count': len(rows),
        'whale_primary_metric': 'history.net_pnl_usd',
        'note': 'WHALE ranks observed BTC history net profit first, then performance score. Other categories use performance score.',
    }
    out['selection_rankings'] = rankings
    return out


def rotate_out_non_top6(state, ranked_cohort, feed, now, category_module):
    """Restrict *new entries* to TOP6, never force-close a live PAPER position.

    A changed score, expired catalog entry or missing observation is not evidence
    that a tracked trader closed their BTC position. Existing positions remain
    monitored until a genuinely observed FLAT/flip or liquidation.
    """
    if not state or not state.get('accounts'):
        return state
    selected = {
        cat: {
            row.get('address')
            for row in ranked_cohort.get('wallets', [])
            if row.get('address') and (row.get('category_flags') or {}).get(cat)
        }
        for cat in CATS
    }
    held_outside_top6 = [
        {'account': key, 'category': a.get('category'), 'wallet': wallet}
        for key, a in state.get('accounts', {}).items()
        for wallet in (a.get('positions') or {})
        if a.get('category') in selected and wallet not in selected[a['category']]
    ]
    state['selection_rotation_policy'] = 'ENTRY_ONLY_HOLD_UNTIL_VERIFIED_SOURCE_EXIT'
    state['selection_rotation_deferred_count'] = len(held_outside_top6)
    state['selection_rotation_deferred'] = held_outside_top6[:300]
    return state
