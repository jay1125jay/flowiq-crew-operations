import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

SPORTS = ('HORSE', 'CYCLE', 'BOAT', 'BULL')
DYNAMIC_OUTCOME_KEYS = (
    'model_p', 'model_source', 'model_updated_at',
    'odds', 'odds_source', 'odds_capture_mode', 'odds_observed_at',
    'final_rank',
)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def git_history_candidates(path: str, limit: int = 80):
    try:
        raw = subprocess.check_output(
            ['git', 'log', f'-n{limit}', '--format=%H', '--', path],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return
    for sha in [x.strip() for x in raw.splitlines() if x.strip()]:
        try:
            text = subprocess.check_output(
                ['git', 'show', f'{sha}:{path}'],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            yield sha, json.loads(text)
        except Exception:
            continue


def find_last_good(current: dict, current_path: Path, previous_path: Path | None):
    date = current.get('date')
    if previous_path and previous_path.exists():
        p = load_json(previous_path)
        # An empty same-day snapshot is still a valid baseline. Requiring at least
        # one event made the guard self-test fail on legitimate no-card days and
        # blocked the entire refresh pipeline before collection could start.
        if isinstance(p, dict) and p.get('date') == date and isinstance(p.get('events', []), list):
            return 'WORKTREE_BACKUP', p
    for sha, payload in git_history_candidates(str(current_path)):
        if payload.get('date') == date and payload.get('events'):
            return sha, payload
    return None, None


def merge_hist(old_hist, new_hist):
    rows = []
    seen = set()
    for x in (old_hist or []) + (new_hist or []):
        key = (x.get('observed_at'), x.get('market'), json.dumps(x.get('odds', {}), sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        rows.append(x)
    return rows[-120:]


def merge_event(old: dict, new: dict):
    """Preserve durable fields only when the current official collector still publishes the same event."""
    out = deepcopy(new)
    if old.get('result') and not out.get('result'):
        out['result'] = deepcopy(old['result'])
        out['status'] = 'FINAL'
    old_outcomes = {o.get('key'): o for o in old.get('outcomes', []) if o.get('key')}
    for o in out.get('outcomes', []):
        prev = old_outcomes.get(o.get('key'))
        if not prev:
            continue
        for k in DYNAMIC_OUTCOME_KEYS:
            if o.get(k) is None and prev.get(k) is not None:
                o[k] = deepcopy(prev[k])
    hist = merge_hist(old.get('odds_history'), out.get('odds_history'))
    if hist:
        out['odds_history'] = hist
    for k in ('stale', 'stale_reason', 'stale_since', 'last_good_generated_at'):
        out.pop(k, None)
    out['data_state'] = 'FRESH'
    return out


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: snapshot_guard.py CURRENT_JSON [PREVIOUS_JSON]')
    current_path = Path(sys.argv[1])
    previous_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    current = load_json(current_path)
    if not current:
        raise SystemExit('CURRENT_SNAPSHOT_INVALID')

    source_ref, previous = find_last_good(current, current_path, previous_path)
    providers = [deepcopy(p) for p in current.get('providers', []) if p.get('provider') != 'SNAPSHOT_GUARD']
    if previous is None:
        providers.append({
            'provider': 'SNAPSHOT_GUARD',
            'status': 'NO_BASELINE',
            'detail': {'recovered': 0, 'policy': 'CURRENT_SOURCE_AUTHORITATIVE_NO_PHANTOM_RECOVERY'},
        })
        current['providers'] = providers
        current['integrity'] = {
            'policy': 'CURRENT_SOURCE_AUTHORITATIVE_NO_PHANTOM_RECOVERY',
            'recovered_events': 0,
            'suppressed_previous_only_events': 0,
            'stale_events': 0,
        }
        current_path.write_text(json.dumps(current, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        print(json.dumps({'status': 'NO_BASELINE', 'events': len(current.get('events', []))}, ensure_ascii=False))
        return

    cur_map = {e.get('id'): e for e in current.get('events', []) if e.get('id')}
    prev_map = {e.get('id'): e for e in previous.get('events', []) if e.get('id')}
    merged = []
    for eid, event in cur_map.items():
        old = prev_map.get(eid)
        merged.append(merge_event(old, event) if old else event)

    previous_only = [eid for eid in prev_map if eid not in cur_map]
    suppressed_by_sport = {s: 0 for s in SPORTS}
    for eid in previous_only:
        sport = prev_map[eid].get('sport')
        if sport in suppressed_by_sport:
            suppressed_by_sport[sport] += 1

    providers.append({
        'provider': 'SNAPSHOT_GUARD',
        'status': 'PASS',
        'detail': {
            'recovered': 0,
            'suppressed_previous_only_events': len(previous_only),
            'suppressed_by_sport': suppressed_by_sport,
            'last_good_source': source_ref,
            'policy': 'CURRENT_SOURCE_AUTHORITATIVE_NO_PHANTOM_RECOVERY',
        },
    })

    merged.sort(key=lambda e: (e.get('start_time', '99:99'), e.get('sport', ''), e.get('id', '')))
    current['events'] = merged
    current['providers'] = providers
    current['integrity'] = {
        'policy': 'CURRENT_SOURCE_AUTHORITATIVE_NO_PHANTOM_RECOVERY',
        'recovered_events': 0,
        'suppressed_previous_only_events': len(previous_only),
        'source_ref': source_ref,
        'stale_events': 0,
    }
    current_path.write_text(json.dumps(current, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({
        'status': 'PASS',
        'events': len(merged),
        'recovered': 0,
        'suppressed_previous_only_events': len(previous_only),
        'suppressed_by_sport': suppressed_by_sport,
        'source_ref': source_ref,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
