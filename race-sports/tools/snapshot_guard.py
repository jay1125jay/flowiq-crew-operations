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
    candidates = []
    if previous_path and previous_path.exists():
        p = load_json(previous_path)
        if p:
            candidates.append(('WORKTREE_BACKUP', p))
    for item in candidates:
        if item[1].get('date') == date and item[1].get('events'):
            return item
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
    out.pop('stale', None)
    out.pop('stale_reason', None)
    out.pop('stale_since', None)
    out.pop('last_good_generated_at', None)
    out['data_state'] = 'FRESH'
    return out


def stale_copy(event: dict, current: dict, previous: dict, reason: str):
    e = deepcopy(event)
    e['stale'] = True
    e['data_state'] = 'STALE_LAST_KNOWN_GOOD'
    e['stale_reason'] = reason
    e['stale_since'] = current.get('generated_at')
    e['last_good_generated_at'] = previous.get('generated_at')
    return e


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: snapshot_guard.py CURRENT_JSON [PREVIOUS_JSON]')
    current_path = Path(sys.argv[1])
    previous_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    current = load_json(current_path)
    if not current:
        raise SystemExit('CURRENT_SNAPSHOT_INVALID')

    source_ref, previous = find_last_good(current, current_path, previous_path)
    if not previous:
        providers = [p for p in current.get('providers', []) if p.get('provider') != 'SNAPSHOT_GUARD']
        providers.append({'provider': 'SNAPSHOT_GUARD', 'status': 'NO_BASELINE', 'detail': {'recovered': 0}})
        current['providers'] = providers
        current_path.write_text(json.dumps(current, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        print(json.dumps({'status': 'NO_BASELINE', 'events': len(current.get('events', []))}, ensure_ascii=False))
        return

    cur_map = {e.get('id'): e for e in current.get('events', []) if e.get('id')}
    prev_map = {e.get('id'): e for e in previous.get('events', []) if e.get('id')}
    merged = []
    recovered_by_sport = {s: 0 for s in SPORTS}

    for eid, event in cur_map.items():
        old = prev_map.get(eid)
        merged.append(merge_event(old, event) if old else event)

    present = {e.get('id') for e in merged}
    for eid, old in prev_map.items():
        if eid in present:
            continue
        sport = old.get('sport')
        if sport not in SPORTS:
            continue
        merged.append(stale_copy(old, current, previous, 'CURRENT_COLLECTION_MISSING_EVENT'))
        recovered_by_sport[sport] += 1

    # If a sport vanished entirely in the current cycle, make the provider state explicit.
    providers = [deepcopy(p) for p in current.get('providers', []) if p.get('provider') != 'SNAPSHOT_GUARD']
    provider_prefix = {'HORSE': 'HORSE_', 'CYCLE': 'CYCLE_', 'BOAT': 'BOAT_KBOAT', 'BULL': 'BULL_'}
    for sport, n in recovered_by_sport.items():
        if n <= 0:
            continue
        for p in providers:
            name = str(p.get('provider', ''))
            prefix = provider_prefix[sport]
            match = name == prefix if sport == 'BOAT' else name.startswith(prefix)
            if match:
                detail = deepcopy(p.get('detail') or {})
                detail.update({'recovered_events': n, 'last_good_source': source_ref})
                p['detail'] = detail
                if p.get('status') in ('FAIL', 'NO_TODAY_CARD', 'WAITING') or sport == 'BOAT':
                    p['status'] = 'STALE_RECOVERED'

    recovered_total = sum(recovered_by_sport.values())
    providers.append({
        'provider': 'SNAPSHOT_GUARD',
        'status': 'RECOVERED' if recovered_total else 'PASS',
        'detail': {
            'recovered': recovered_total,
            'by_sport': recovered_by_sport,
            'last_good_source': source_ref,
            'policy': 'SAME_DAY_LAST_KNOWN_GOOD_NEVER_DROP',
        },
    })

    merged.sort(key=lambda e: (e.get('start_time', '99:99'), e.get('sport', ''), e.get('id', '')))
    current['events'] = merged
    current['providers'] = providers
    current['integrity'] = {
        'policy': 'LAST_KNOWN_GOOD',
        'recovered_events': recovered_total,
        'source_ref': source_ref,
        'stale_events': sum(1 for e in merged if e.get('stale')),
    }
    current_path.write_text(json.dumps(current, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({
        'status': 'RECOVERED' if recovered_total else 'PASS',
        'events': len(merged),
        'recovered': recovered_total,
        'by_sport': recovered_by_sport,
        'source_ref': source_ref,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
