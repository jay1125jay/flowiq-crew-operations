#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import validate_horse_model as hv

OUT = Path('race-sports/models/horse_win_quinella_compare.json')
PAYOUTS = Path('race-sports/data/model_state/horse_quinella_payouts.json')
KST = timezone(timedelta(hours=9))
STAKE = 100000
VERSION = 'HORSE_WIN_QUINELLA_COMPARE_V2_SAME_SAMPLE_ROI'


def rank_index(event, rank):
    for i, o in enumerate(event.get('outcomes') or []):
        try:
            if int(o.get('final_rank')) == rank:
                return i
        except Exception:
            pass
    return None


def load_payouts():
    if not PAYOUTS.exists():
        return {}
    try:
        d = json.loads(PAYOUTS.read_text(encoding='utf-8'))
        return d.get('records') if isinstance(d.get('records'), dict) else {}
    except Exception:
        return {}


def run():
    races = hv.records()
    payouts = load_payouts()
    stats = {'horse': defaultdict(lambda:[0,0]), 'jockey': defaultdict(lambda:[0,0]), 'trainer': defaultdict(lambda:[0,0])}
    total_starts = total_wins = 0
    warmup = max(100, int(len(races) * .30)) if races else 0

    win_tests = win_hits = 0
    quinella_tests = quinella_hits = 0
    win_odds_tests = 0
    win_staked = win_return = 0.0

    same_n = same_win_hits = same_q_hits = 0
    same_win_return = same_q_return = 0.0

    for i, e in enumerate(races):
        outs = e.get('outcomes') or []
        base = (total_wins / total_starts) if total_starts else .10
        if i >= warmup and len(outs) >= 2:
            probs = hv.score(e, stats, base)
            first = rank_index(e, 1)
            second = rank_index(e, 2)
            if probs and first is not None:
                order = sorted(range(len(probs)), key=lambda j: probs[j], reverse=True)
                pred1 = order[0]
                hit = pred1 == first
                win_tests += 1
                win_hits += int(hit)
                try: odds = float(outs[pred1].get('final_odds'))
                except Exception: odds = 0.0
                if odds > 0:
                    win_odds_tests += 1; win_staked += STAKE
                    if hit: win_return += STAKE * odds

                q_hit = False
                if second is not None and len(order) >= 2:
                    quinella_tests += 1
                    q_hit = {order[0], order[1]} == {first, second}
                    quinella_hits += int(q_hit)

                    # Fair ROI comparison: only races where official KRA quinella payout exists,
                    # and compare both strategies on exactly that same race set.
                    pr = payouts.get(str(e.get('id'))) or {}
                    try: q_odds = float(pr.get('quinella_odds'))
                    except Exception: q_odds = 0.0
                    if q_odds > 0 and odds > 0:
                        same_n += 1
                        same_win_hits += int(hit); same_q_hits += int(q_hit)
                        if hit: same_win_return += STAKE * odds
                        if q_hit: same_q_return += STAKE * q_odds

        s, w = hv.update(stats, e)
        total_starts += s; total_wins += w

    win_rate = win_hits / win_tests if win_tests else None
    q_rate = quinella_hits / quinella_tests if quinella_tests else None
    win_profit = win_return - win_staked
    same_staked = same_n * STAKE
    sw_profit = same_win_return - same_staked
    sq_profit = same_q_return - same_staked
    fair_state = 'PASS_SAME_SAMPLE_OFFICIAL_FINAL_TOTE_ODDS' if same_n else 'BLOCKED_UNTIL_QUINELLA_PAYOUT_HISTORY_IS_AVAILABLE'
    out = {
        'version': VERSION,
        'generated_at': datetime.now(KST).isoformat(timespec='seconds'),
        'model_source': hv.MODEL_SOURCE,
        'method': 'SAME_CHRONOLOGICAL_WALK_FORWARD_MODEL; FIRST_30PCT_WARMUP; NO_POSTRACE_FIELDS_IN_PREDICTION',
        'input_races': len(races), 'warmup_races': warmup,
        'win': {
            'definition': 'MODEL_TOP1_EQUALS_OFFICIAL_1ST', 'tested': win_tests, 'hits': win_hits,
            'hit_rate': round(win_rate, 8) if win_rate is not None else None,
            'paper_100k_at_official_final_win_odds': {
                'odds_available_races': win_odds_tests, 'total_staked_krw': int(win_staked),
                'total_return_krw': round(win_return), 'net_profit_krw': round(win_profit),
                'roi': round(win_profit / win_staked, 8) if win_staked else None,
                'warning': 'USES_OFFICIAL_FINAL_TOTE_WIN_ODDS; NOT PRE-RACE_LOCKED_ODDS'
            }
        },
        'quinella': {
            'definition': 'MODEL_TOP2_PAIR_EQUALS_OFFICIAL_1ST_AND_2ND; ORDER_IGNORED',
            'tested': quinella_tests, 'hits': quinella_hits,
            'hit_rate': round(q_rate, 8) if q_rate is not None else None,
        },
        'fair_same_sample_roi': {
            'state': fair_state,
            'sample_races': same_n,
            'stake_per_race_krw_each_strategy': STAKE,
            'win': {
                'hits': same_win_hits,
                'hit_rate': round(same_win_hits/same_n, 8) if same_n else None,
                'total_staked_krw': same_staked,
                'total_return_krw': round(same_win_return),
                'net_profit_krw': round(sw_profit) if same_n else None,
                'roi': round(sw_profit/same_staked, 8) if same_staked else None,
            },
            'quinella': {
                'hits': same_q_hits,
                'hit_rate': round(same_q_hits/same_n, 8) if same_n else None,
                'total_staked_krw': same_staked,
                'total_return_krw': round(same_q_return),
                'net_profit_krw': round(sq_profit) if same_n else None,
                'roi': round(sq_profit/same_staked, 8) if same_staked else None,
            },
            'winner_by_roi': ('WIN' if same_n and sw_profit > sq_profit else ('QUINELLA' if same_n and sq_profit > sw_profit else ('TIE' if same_n else None))),
            'warning': 'OFFICIAL FINAL TOTE SETTLEMENT ODDS; THIS IS SETTLEMENT-REFERENCE BACKTEST, NOT PRE-RACE PRICE-LOCKED EXECUTION'
        },
        'comparison': {
            'easier_by_observed_hit_rate': 'WIN' if win_rate is not None and q_rate is not None and win_rate > q_rate else ('QUINELLA' if win_rate is not None and q_rate is not None and q_rate > win_rate else 'TIE_OR_UNAVAILABLE'),
            'hit_rate_gap_percentage_points_win_minus_quinella': round((win_rate - q_rate) * 100, 4) if win_rate is not None and q_rate is not None else None,
            'fair_profit_comparison_state': fair_state
        },
        'policy': 'HIT_RATE_USES_FULL_WALK_FORWARD; ROI_COMPARE_USES_EXACT_SAME_RACES_WITH_OFFICIAL_KRA_FINAL_TOTE_ODDS; NO_SYNTHETIC_ODDS'
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'HORSE_WIN_QUINELLA_COMPARE':'PASS', **out['comparison'], 'same_sample':out['fair_same_sample_roi']}, ensure_ascii=False))


if __name__ == '__main__':
    run()
