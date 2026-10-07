import json
import math
import sys
from datetime import datetime, timedelta, timezone
from collections import Counter
from pathlib import Path

KST = timezone(timedelta(hours=9))


def fail(msg):
    print('VALIDATION_FAIL=' + msg)
    raise SystemExit(2)


def parse_ts(v):
    try:
        return datetime.fromisoformat(str(v).replace('Z', '+00:00'))
    except Exception:
        return None


def event_start_ts(payload, event):
    date = str(event.get('event_date') or payload.get('date') or '')
    start = str(event.get('start_time') or '')
    try:
        return datetime.fromisoformat(f'{date}T{start}:00').replace(tzinfo=KST)
    except Exception:
        return None


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else 'race-sports/data/today.json')
    try:
        p = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        fail('JSON:' + str(e))

    events = p.get('events') or []
    ids = [e.get('id') for e in events if e.get('id')]
    if len(ids) != len(set(ids)):
        fail('DUPLICATE_EVENT_ID')

    # KBOAT has one race number per actual race date. Different meeting-day IDs
    # for the same date/race number are phantom duplicates, even when IDs differ.
    boat_keys = []
    for e in events:
        if e.get('sport') == 'BOAT':
            boat_keys.append((e.get('event_date'), e.get('race_no')))
    if len(boat_keys) != len(set(boat_keys)):
        fail('BOAT_LOGICAL_DUPLICATE_DATE_RACE')

    sports = Counter(e.get('sport') for e in events)
    stale_events = [e.get('id') for e in events if e.get('stale') or e.get('data_state') == 'STALE_LAST_KNOWN_GOOD']
    if stale_events:
        fail('STALE_EVENTS_FORBIDDEN:' + str(stale_events[:5]))

    generated = parse_ts(p.get('generated_at'))
    if generated is not None:
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=KST)
        generated = generated.astimezone(KST)
        impossible = []
        for e in events:
            if e.get('status') != 'SCHEDULED':
                continue
            start_at = event_start_ts(p, e)
            if start_at and generated - start_at > timedelta(minutes=5):
                impossible.append((e.get('id'), e.get('start_time')))
        if impossible:
            fail('PAST_EVENT_STILL_SCHEDULED:' + str(impossible[:5]))

    bad_odds = []
    bad_model = []
    bad_model_state = []
    bad_bull = []
    bad_bull_result = []
    bad_bull_odds = []
    bad_bull_capture = []
    bad_bull_model = []

    for e in events:
        outcomes = e.get('outcomes', [])
        model_values = [o.get('model_p') for o in outcomes]
        populated = [v for v in model_values if v is not None]
        if populated:
            try:
                vals = [float(v) for v in populated]
                if not all(math.isfinite(v) and 0.0 <= v <= 1.0 for v in vals):
                    bad_model.append((e.get('id'), 'MODEL_RANGE'))
                needs_full_distribution = e.get('sport') == 'BULL' or e.get('status') == 'SCHEDULED'
                if needs_full_distribution:
                    if len(populated) != len(outcomes):
                        bad_model.append((e.get('id'), 'PARTIAL_MODEL'))
                    elif abs(sum(vals) - 1.0) > 0.03:
                        bad_model.append((e.get('id'), f'MODEL_SUM:{sum(vals):.6f}'))
            except Exception:
                bad_model.append((e.get('id'), 'MODEL_PARSE'))

        if e.get('model_stale') and e.get('value_enabled'):
            bad_model_state.append((e.get('id'), 'STALE_MODEL_VALUE_ENABLED'))
        if e.get('model_incomplete') and e.get('value_enabled'):
            bad_model_state.append((e.get('id'), 'INCOMPLETE_MODEL_VALUE_ENABLED'))

        if e.get('sport') == 'BULL':
            keys = [o.get('key') for o in outcomes]
            if keys and keys != ['RED', 'DRAW', 'BLUE']:
                bad_bull.append(e.get('id'))

            winner = ((e.get('result') or {}).get('winner') or {}).get('key')
            if winner is not None and winner not in ('RED', 'DRAW', 'BLUE'):
                bad_bull_result.append((e.get('id'), winner))

            cpc = [o for o in outcomes if o.get('odds_source') == 'CPC_FINAL_SINGLE_AUTO']
            if cpc:
                cmap = {o.get('key'): o for o in cpc}
                if set(cmap) != {'RED', 'DRAW', 'BLUE'}:
                    bad_bull_odds.append((e.get('id'), 'MISSING_THREE_WAY'))
                else:
                    for key in ('RED', 'DRAW', 'BLUE'):
                        try:
                            if float(cmap[key].get('odds') or 0) <= 0:
                                bad_bull_odds.append((e.get('id'), key))
                        except Exception:
                            bad_bull_odds.append((e.get('id'), key))

                result_at = parse_ts(((e.get('result') or {}).get('updated_at')))
                for o in cpc:
                    mode = o.get('odds_capture_mode')
                    if mode not in ('PRE_RACE_OFFICIAL', 'LATE_OFFICIAL_RECOVERY'):
                        bad_bull_capture.append((e.get('id'), o.get('key'), 'MODE'))
                    odds_at = parse_ts(o.get('odds_observed_at'))
                    if mode == 'PRE_RACE_OFFICIAL' and result_at and odds_at and odds_at >= result_at:
                        bad_bull_capture.append((e.get('id'), o.get('key'), 'PRE_AT_OR_AFTER_RESULT'))

                if result_at:
                    for h in e.get('odds_history', []) or []:
                        if h.get('source') != 'CPC_FINAL_SINGLE_AUTO':
                            continue
                        hist_at = parse_ts(h.get('observed_at'))
                        if h.get('capture_mode') == 'PRE_RACE_OFFICIAL' and hist_at and hist_at >= result_at:
                            bad_bull_capture.append((e.get('id'), 'HISTORY', 'PRE_AT_OR_AFTER_RESULT'))

            if populated:
                sources = {o.get('model_source') for o in outcomes}
                if sources != {'bull_threeclass_direct_v1.3.0'}:
                    bad_bull_model.append((e.get('id'), sorted(str(x) for x in sources)))

        for o in outcomes:
            if o.get('odds') is not None:
                try:
                    if float(o['odds']) <= 0:
                        bad_odds.append((e.get('id'), o.get('key')))
                except Exception:
                    bad_odds.append((e.get('id'), o.get('key')))

    if bad_odds:
        fail('NON_POSITIVE_ODDS')
    if bad_model:
        fail('MODEL_PROBABILITY:' + str(bad_model[:3]))
    if bad_model_state:
        fail('MODEL_STATE:' + str(bad_model_state[:3]))
    if bad_bull:
        fail('BULL_OUTCOME_ORDER')
    if bad_bull_result:
        fail('BULL_RESULT_KEY')
    if bad_bull_odds:
        fail('BULL_THREE_WAY_ODDS')
    if bad_bull_capture:
        fail('BULL_CAPTURE_MODE:' + str(bad_bull_capture[:3]))
    if bad_bull_model:
        fail('BULL_MODEL_SOURCE')

    hard_provider_states = {'FAIL', 'ERROR', 'STALE_RECOVERED', 'RECOVERED'}
    bad_providers = [
        (x.get('provider'), x.get('status'))
        for x in p.get('providers', [])
        if x.get('status') in hard_provider_states
    ]
    if bad_providers:
        fail('HARD_PROVIDER_STATE:' + str(bad_providers[:5]))

    guard = next((x for x in p.get('providers', []) if x.get('provider') == 'SNAPSHOT_GUARD'), None)
    if guard and guard.get('status') not in {'PASS', 'NO_BASELINE'}:
        fail('SNAPSHOT_GUARD_NOT_CLEAN:' + str(guard.get('status')))

    print(json.dumps({
        'VALIDATION': 'PASS',
        'date': p.get('date'),
        'events': len(events),
        'by_sport': dict(sports),
        'stale_events': 0,
        'guard': (guard or {}).get('status'),
        'boat_logical_duplicate_guard': True,
        'past_scheduled_guard': True,
        'active_model_probability_guard': True,
        'model_state_guard': True,
        'post_start_model_history_tolerates_scratches': True,
        'result_publish_not_blocked_by_post_start_model': True,
        'bull_three_way_guard': True,
        'bull_capture_mode_guard': True,
        'bull_model_source_guard': True,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
