#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import validate_horse_model as hv

OUT = Path('race-sports/models/horse_win_quinella_compare.json')
KST = timezone(timedelta(hours=9))
STAKE = 100000
VERSION = 'HORSE_WIN_QUINELLA_COMPARE_V1_WALK_FORWARD'


def rank_index(event, rank):
    for i, o in enumerate(event.get('outcomes') or []):
        try:
            if int(o.get('final_rank')) == rank:
                return i
        except Exception:
            pass
    return None


def run():
    races = hv.records()
    stats = {'horse': defaultdict(lambda:[0,0]), 'jockey': defaultdict(lambda:[0,0]), 'trainer': defaultdict(lambda:[0,0])}
    total_starts = total_wins = 0
    warmup = max(100, int(len(races) * .30)) if races else 0

    win_tests = win_hits = 0
    quinella_tests = quinella_hits = 0
    win_odds_tests = 0
    win_staked = win_return = 0.0

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
                win_tests += 1
                hit = pred1 == first
                win_hits += int(hit)

                # Official final win odds are stored by KRA. This is a tote-settlement
                # reference, not a pre-race locked price; keep it separate from hit-rate comparison.
                try:
                    odds = float(outs[pred1].get('final_odds'))
                except Exception:
                    odds = 0.0
                if odds > 0:
                    win_odds_tests += 1
                    win_staked += STAKE
                    if hit:
                        win_return += STAKE * odds

                if second is not None and len(order) >= 2:
                    quinella_tests += 1
                    predicted_pair = {order[0], order[1]}
                    actual_pair = {first, second}
                    quinella_hits += int(predicted_pair == actual_pair)

        s, w = hv.update(stats, e)
        total_starts += s
        total_wins += w

    win_rate = win_hits / win_tests if win_tests else None
    q_rate = quinella_hits / quinella_tests if quinella_tests else None
    win_profit = win_return - win_staked
    out = {
        'version': VERSION,
        'generated_at': datetime.now(KST).isoformat(timespec='seconds'),
        'model_source': hv.MODEL_SOURCE,
        'method': 'SAME_CHRONOLOGICAL_WALK_FORWARD_MODEL; FIRST_30PCT_WARMUP; NO_POSTRACE_FIELDS_IN_PREDICTION',
        'input_races': len(races),
        'warmup_races': warmup,
        'win': {
            'definition': 'MODEL_TOP1_EQUALS_OFFICIAL_1ST',
            'tested': win_tests,
            'hits': win_hits,
            'hit_rate': round(win_rate, 8) if win_rate is not None else None,
            'paper_100k_at_official_final_win_odds': {
                'odds_available_races': win_odds_tests,
                'total_staked_krw': int(win_staked),
                'total_return_krw': round(win_return),
                'net_profit_krw': round(win_profit),
                'roi': round(win_profit / win_staked, 8) if win_staked else None,
                'warning': 'USES_OFFICIAL_FINAL_TOTE_WIN_ODDS; NOT PRE-RACE_LOCKED_ODDS'
            }
        },
        'quinella': {
            'definition': 'MODEL_TOP2_PAIR_EQUALS_OFFICIAL_1ST_AND_2ND; ORDER_IGNORED',
            'tested': quinella_tests,
            'hits': quinella_hits,
            'hit_rate': round(q_rate, 8) if q_rate is not None else None,
            'paper_roi': None,
            'roi_state': 'UNAVAILABLE_NO_HISTORICAL_QUINELLA_PAYOUT_IN_CURRENT_BACKFILL'
        },
        'comparison': {
            'easier_by_observed_hit_rate': 'WIN' if win_rate is not None and q_rate is not None and win_rate > q_rate else ('QUINELLA' if win_rate is not None and q_rate is not None and q_rate > win_rate else 'TIE_OR_UNAVAILABLE'),
            'hit_rate_gap_percentage_points_win_minus_quinella': round((win_rate - q_rate) * 100, 4) if win_rate is not None and q_rate is not None else None,
            'fair_profit_comparison_state': 'BLOCKED_UNTIL_QUINELLA_PAYOUT_HISTORY_IS_AVAILABLE'
        },
        'policy': 'HIT_RATE_COMPARE_ONLY_FOR_WIN_VS_QUINELLA; DO_NOT_INVENT_QUINELLA_PAYOUT; PROFIT_COMPARISON_REQUIRES_OFFICIAL_QUINELLA_PAYOUT_HISTORY'
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'HORSE_WIN_QUINELLA_COMPARE':'PASS', **out['comparison'], 'win':out['win']['hit_rate'], 'quinella':out['quinella']['hit_rate'], 'tests':{'win':win_tests,'quinella':quinella_tests}}, ensure_ascii=False))


if __name__ == '__main__':
    run()
