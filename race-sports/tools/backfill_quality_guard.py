import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path('race-sports')
BACKFILL = ROOT / 'data' / 'backfill'
STATE_DIR = ROOT / 'data' / 'historical_state'
STATE_FILE = STATE_DIR / 'backfill_state.json'
REPORT_FILE = STATE_DIR / 'backfill_report.json'
QUALITY_FILE = STATE_DIR / 'backfill_quality_report.json'
KST = timezone(timedelta(hours=9))


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def one_winner(outcomes):
    return sum(1 for o in outcomes if o.get('won') is True) == 1


def validate_horse(e):
    outs = list(e.get('outcomes') or [])
    if len(outs) < 5:
        return False, 'HORSE_TOO_FEW_RUNNERS'
    nums = [o.get('number') for o in outs]
    if None in nums or len(set(nums)) != len(nums):
        return False, 'HORSE_DUPLICATE_OR_MISSING_NUMBER'
    if not one_winner(outs):
        return False, 'HORSE_WINNER_COUNT'
    ranks = [o.get('final_rank') for o in outs if o.get('final_rank') is not None]
    if len(ranks) < 3 or len(set(ranks)) != len(ranks):
        return False, 'HORSE_RANKS_INVALID'
    for o in outs:
        name = str(o.get('horse_name') or '').strip()
        if not name or '코너지점' in name or name in {'마명', '순위', '마번'}:
            return False, 'HORSE_NAME_INVALID'
        w = o.get('assigned_weight')
        if w is not None:
            try:
                if not 35.0 <= float(w) <= 70.0:
                    return False, 'HORSE_WEIGHT_INVALID'
            except Exception:
                return False, 'HORSE_WEIGHT_PARSE'
        for key in ('jockey', 'trainer'):
            v = str(o.get(key) or '').strip()
            if v and ('F-G' in v or '코너지점' in v):
                return False, f'HORSE_{key.upper()}_INVALID'
    return True, None


def validate_cycle(e):
    outs = list(e.get('outcomes') or [])
    if len(outs) < 5 or not one_winner(outs):
        return False, 'CYCLE_RUNNERS_OR_WINNER_INVALID'
    top3 = list((e.get('result') or {}).get('top3') or [])
    if len(top3) != 3 or len({x.get('number') for x in top3}) != 3:
        return False, 'CYCLE_TOP3_INVALID'
    return True, None


def validate_boat(e):
    outs = list(e.get('outcomes') or [])
    if len(outs) < 4 or not one_winner(outs):
        return False, 'BOAT_RUNNERS_OR_WINNER_INVALID'
    top3 = list((e.get('result') or {}).get('top3') or [])
    if len(top3) != 3 or len({x.get('number') for x in top3}) != 3:
        return False, 'BOAT_TOP3_INVALID'
    winner = next((o.get('number') for o in outs if o.get('won') is True), None)
    if winner != top3[0].get('number'):
        return False, 'BOAT_WINNER_MISMATCH'
    return True, None


def validate_bull(e):
    outs = list(e.get('outcomes') or [])
    if [o.get('key') for o in outs] != ['RED', 'DRAW', 'BLUE']:
        return False, 'BULL_OUTCOMES_INVALID'
    if not one_winner(outs):
        return False, 'BULL_WINNER_COUNT'
    result_key = ((e.get('result') or {}).get('winner') or {}).get('key')
    won_key = next((o.get('key') for o in outs if o.get('won') is True), None)
    if result_key != won_key:
        return False, 'BULL_WINNER_MISMATCH'
    return True, None


VALIDATORS = {
    'horse': validate_horse,
    'cycle': validate_cycle,
    'boat': validate_boat,
    'bull': validate_bull,
}


def scan_and_clean(sport):
    d = BACKFILL / sport
    kept = 0
    removed = []
    rejected_dates = []
    if not d.exists():
        return kept, removed, rejected_dates
    for path in sorted(d.glob('*.jsonl')):
        good_lines = []
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except Exception:
                removed.append({'id': None, 'reason': 'JSON_PARSE', 'file': str(path)})
                continue
            ok, reason = VALIDATORS[sport](e)
            if ok:
                good_lines.append(json.dumps(e, ensure_ascii=False, separators=(',', ':')))
                kept += 1
            else:
                removed.append({'id': e.get('id'), 'reason': reason, 'file': str(path)})
                if e.get('event_date'):
                    rejected_dates.append(str(e['event_date']))
        if good_lines:
            path.write_text('\n'.join(good_lines) + '\n', encoding='utf-8')
        elif path.exists():
            path.unlink()
    return kept, removed, rejected_dates


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = load_json(STATE_FILE, {})
    report = load_json(REPORT_FILE, {})
    summary = {
        'generated_at': datetime.now(KST).isoformat(timespec='seconds'),
        'status': 'PASS',
        'sports': {},
        'rejected_total': 0,
    }
    totals = {}
    all_removed = []
    for sport in ('horse', 'cycle', 'boat', 'bull'):
        kept, removed, rejected_dates = scan_and_clean(sport)
        totals[sport] = kept
        all_removed.extend([{'sport': sport, **x} for x in removed])
        summary['sports'][sport] = {'kept': kept, 'rejected': len(removed)}
        if sport == 'horse' and rejected_dates:
            cp = (state.get('checkpoints') or {}).get('horse')
            if isinstance(cp, dict):
                retry_date = max(rejected_dates)
                cur = str(cp.get('cursor_date') or '')
                if not cur or cur < retry_date:
                    cp['cursor_date'] = retry_date
                cp['complete'] = False
                summary['sports'][sport]['retry_cursor_date'] = cp.get('cursor_date')
    summary['rejected_total'] = len(all_removed)
    summary['rejected'] = all_removed[:200]

    if state:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    if isinstance(report, dict) and report:
        report['records_total'] = totals
        report['quality_guard'] = {
            'status': 'PASS',
            'rejected_total': len(all_removed),
            'by_sport': {s: summary['sports'][s] for s in summary['sports']},
        }
        REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    QUALITY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    print(json.dumps({'BACKFILL_QUALITY': 'PASS', 'totals': totals, 'rejected': len(all_removed)}, ensure_ascii=False))
    if summary['sports']['horse']['rejected']:
        print('HORSE_BACKFILL_REJECTED_AND_RETRY_ENABLED=TRUE')


if __name__ == '__main__':
    main()
