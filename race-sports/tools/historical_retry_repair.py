"""Lossless retry scheduling: HTTP/parser failures never prove a race absent."""
from __future__ import annotations
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import re

KST = timezone(timedelta(hours=9))


def key(item):
    d = date.fromisoformat(str(item.get('date')))
    meet = str(item.get('meet'))
    race = int(item.get('race_no'))
    if meet not in {'1', '2', '3', '4'} or not 1 <= race <= 16:
        raise ValueError('INVALID_RETRY_KEY')
    return d, meet, race


def attempts(item):
    try:
        return max(0, int(item.get('attempts', 0)))
    except (ValueError, TypeError):
        return 0


def delay(n):
    return timedelta(days=min(14, 2 ** min(4, max(0, n - 1))))


def classify(item):
    error = str(item.get('last_error', ''))
    if 'MISMATCH' in error:
        return 'UNRESOLVED_PAGE_OR_PARSER'
    if error:
        return 'TRANSIENT_FETCH_FAILURE'
    return 'UNTRIED'


def prepare(state, seen, now):
    unique = {}
    duplicates = resolved = 0
    for original in state.setdefault('retry_queue', {}).setdefault('horse', []):
        item = dict(original)
        try:
            d, meet, race = key(item)
        except (ValueError, TypeError):
            state.setdefault('retry_dead_letter', {}).setdefault('horse', []).append({**item, 'reason':'MALFORMED_RETRY_ITEM'})
            continue
        eid = f'HORSE-{d:%Y%m%d}-M{meet}-{race:02d}'
        if eid in seen:
            resolved += 1
            continue
        item.update(date=d.isoformat(), meet=meet, race_no=race, attempts=attempts(item))
        item.setdefault('classification', classify(item))
        # Legacy failures have no attempt time. Start a bounded cooldown once;
        # keep every unresolved key, including repeated parser mismatches.
        if not item.get('next_retry_at'):
            item['next_retry_at'] = (now + delay(attempts(item)) if attempts(item) else now).isoformat()
        try:
            due = datetime.fromisoformat(item['next_retry_at'])
            if due.tzinfo is None:
                raise ValueError('NAIVE_RETRY_TIME')
        except (TypeError, ValueError):
            item['next_retry_at'] = now.isoformat()
        if eid in unique:
            duplicates += 1
            if attempts(unique[eid]) >= attempts(item):
                continue
        unique[eid] = item
    queue = sorted(unique.values(), key=lambda x: datetime.fromisoformat(x['next_retry_at']))
    state['retry_queue']['horse'] = queue
    return queue, duplicates, resolved


def install(hb):
    original = hb.backfill_horse

    def repair_then_backfill(state, budget, seen, stats):
        now = datetime.now(KST)
        queue, duplicates, resolved = prepare(state, seen, now)
        attempted = recovered = 0
        # One network attempt per due item; reserve 90% for new history.
        limit = min(40, max(0, budget.available('horse') // 10))
        for item in list(queue):
            if attempted >= limit or not budget.time_left() or budget.available('horse') <= 0:
                break
            if datetime.fromisoformat(item['next_retry_at']) > now:
                continue
            d, meet, race = key(item)
            attempted += 1
            event = None
            try:
                raw = hb.fetch(hb.HORSE_DETAIL.format(meet=meet, ymd=d.strftime('%Y%m%d'), race=race), budget, 'horse', timeout=12, retries=1)
                _, text = hb.parse_html(raw)
                meta = re.search(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일[\s\S]{0,1800}?제\s*(\d{1,2})경주', text)
                if not meta:
                    item['classification'] = 'UNRESOLVED_NO_RACE_METADATA'
                elif date(*map(int, meta.groups()[:3])) != d or int(meta.group(4)) != race:
                    item['classification'] = 'UNRESOLVED_RENDERED_RACE_MISMATCH'
                else:
                    event = hb.parse_horse_detail(raw, meet, d, race)
                    item['classification'] = 'UNRESOLVED_PARSER_REJECTED'
                if event:
                    expected = f'HORSE-{d:%Y%m%d}-M{meet}-{race:02d}'
                    if event.get('id') != expected:
                        event = None
                        item['classification'] = 'UNRESOLVED_EVENT_ID_MISMATCH'
            except Exception as exc:
                item['classification'] = 'TRANSIENT_FETCH_FAILURE'
                item['last_error'] = type(exc).__name__
            if event:
                hb.append_record('horse', event)
                seen.add(event['id'])
                queue.remove(item)
                recovered += 1
            else:
                item['attempts'] = attempts(item) + 1
                item['last_attempt_at'] = now.isoformat()
                item['next_retry_at'] = (now + delay(item['attempts'])).isoformat()
                item['last_error'] = item['classification']
        stats['horse_retry_attempted'] = stats.get('horse_retry_attempted', 0) + attempted
        stats['horse_retry_recovered'] = stats.get('horse_retry_recovered', 0) + recovered
        # The forward collector can append more failures; summarize afterwards.
        original(state, budget, seen, stats)
        queue, extra_duplicates, extra_resolved = prepare(state, seen, now)
        state.setdefault('retry_metrics', {})['horse'] = {
            'attempted_this_run': attempted, 'recovered_this_run': recovered,
            'remaining': len(queue), 'deferred': sum(datetime.fromisoformat(x['next_retry_at']) > now for x in queue),
            'due': sum(datetime.fromisoformat(x['next_retry_at']) <= now for x in queue),
            'duplicates_removed': duplicates + extra_duplicates,
            'already_saved_removed': resolved + extra_resolved,
            'by_classification': dict(Counter(x['classification'] for x in queue)),
            'policy': 'NO_ABSENCE_INFERENCE_KEEP_UNRESOLVED_BACKOFF_1_TO_14_DAYS',
        }
        hb.save_state(state)
    hb.backfill_horse = repair_then_backfill
    return hb


def self_test():
    from types import SimpleNamespace
    now = datetime.now(KST)
    item = {'date':'2024-02-02', 'meet':'3', 'race_no':10, 'attempts':31, 'last_error':'PARSE_OR_RENDERED_RACE_MISMATCH'}
    state = {'retry_queue':{'horse':[item, dict(item)]}}
    q, dup, _ = prepare(state, set(), now)
    assert len(q) == 1 and dup == 1 and datetime.fromisoformat(q[0]['next_retry_at']) == now + timedelta(days=14)
    assert prepare(state, set(), now + timedelta(days=1))[0][0]['next_retry_at'] == q[0]['next_retry_at']
    assert not prepare(state, {'HORSE-20240202-M3-10'}, now)[0]
    for mode in ('valid', 'wrong_date', 'timeout', 'no_metadata'):
        saved = []
        def fetch(*args, **kwargs):
            if mode == 'timeout': raise TimeoutError()
            return 'raw'
        text = '2024년 02월 02일 제 10경주' if mode == 'valid' else ('2024년 02월 03일 제 10경주' if mode == 'wrong_date' else '')
        hb = SimpleNamespace(backfill_horse=lambda *a:None, fetch=fetch, parse_html=lambda r:(None,text), parse_horse_detail=lambda *a:{'id':'HORSE-20240202-M3-10'}, append_record=lambda s,e:saved.append(e), save_state=lambda s:None, HORSE_DETAIL='{meet}/{ymd}/{race}')
        budget = SimpleNamespace(available=lambda s:100, time_left=lambda:True)
        state = {'retry_queue':{'horse':[{**item, 'attempts':0}]}}
        install(hb).backfill_horse(state,budget,set(),{})
        assert bool(saved) == (mode == 'valid')
        assert len(state['retry_queue']['horse']) == (0 if mode == 'valid' else 1)
        if mode != 'valid': assert state['retry_metrics']['horse']['deferred'] == 1
    print('HISTORICAL_RETRY_REPAIR_SELF_TEST=PASS cases=7')

if __name__ == '__main__': self_test()
