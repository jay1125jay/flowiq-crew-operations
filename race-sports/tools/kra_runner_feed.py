import time
from kra_official_enricher import RUNNERS_URL, MEET_CODE, fetch, parse_runners, venue_of
from kra_final_runner_repair import repair_doc

PROVIDER = 'HORSE_RUNNERS_KRA'


def _runner_urls(venue, today):
    meet = MEET_CODE.get(venue)
    if not meet:
        return []
    ts = str(int(time.time()))
    sub = {'서울': '2', '제주': '3', '부경': '4', '부산경남': '4', '영천': '5'}.get(venue, '1')
    ymd = today.replace('-', '')
    # Use venue-qualified KRA tabs first. Date-qualified variants are tried
    # before generic URLs, but a response is accepted only when the page itself
    # identifies today's date. We never infer date identity from start times.
    return [
        f'{RUNNERS_URL}?Act=02&Sub={sub}&meet={meet}&rcDate={ymd}&_ts={ts}',
        f'{RUNNERS_URL}?Act=02&Sub={sub}&meet={meet}&realRcDate={ymd}&_ts={ts}',
        f'{RUNNERS_URL}?Act=02&Sub={sub}&meet={meet}&searchDate={ymd}&_ts={ts}',
        f'{RUNNERS_URL}?Act=02&Sub={sub}&meet={meet}&_ts={ts}',
        f'{RUNNERS_URL}?meet={meet}&_ts={ts}',
    ]


def _merge_outcomes(event, incoming):
    old = {o.get('key'): o for o in event.get('outcomes', []) if o.get('key')}
    merged = []
    preserve = (
        'model_p','model_source','model_updated_at','model_state','model_validated',
        'odds','odds_source','odds_capture_mode','odds_observed_at',
        'final_rank','final_odds','final_place_odds','final_odds_source',
    )
    for o in incoming:
        q = old.get(o.get('key'), {})
        for k in preserve:
            if q.get(k) is not None:
                o[k] = q[k]
        merged.append(o)
    event['outcomes'] = merged


def enrich_doc(doc):
    # The generic KRA runner page may expose a stale selected date. Purge that
    # data first and rebuild completed races from explicit date+meet+race result
    # detail URLs, which are safe against cross-day runner leakage.
    repaired, final_count, cleared, repair_errors, repair_status = repair_doc(doc)

    today = str(doc.get('date') or '')
    horse = [e for e in doc.get('events', []) if e.get('sport') == 'HORSE']
    venues = []
    for e in horse:
        v = venue_of(e)
        if v and v not in venues:
            venues.append(v)

    accepted = {}
    source_meta = []
    errors = []

    for venue in venues:
        venue_events = {
            (venue, int(e.get('race_no') or 0)): e
            for e in horse if venue_of(e) == venue
        }
        best = {}
        best_meta = None
        for url in _runner_urls(venue, today):
            try:
                raw = fetch(url, timeout=8, retries=1)
                page_date, races = parse_runners(raw)
                usable = {}
                if page_date == today:
                    for key, event in venue_events.items():
                        info = races.get(key)
                        if not info or not info.get('outcomes'):
                            continue
                        src_time = info.get('start_time')
                        dst_time = event.get('start_time')
                        if src_time and dst_time and src_time != dst_time:
                            continue
                        usable[key] = info
                meta = {
                    'venue': venue,
                    'url': url,
                    'page_date': page_date,
                    'raw_races': len(races),
                    'trusted_races': len(usable),
                    'date_verified': page_date == today,
                }
                if len(usable) > len(best):
                    best = usable
                    best_meta = meta
                if page_date == today and len(usable) >= len(venue_events):
                    break
            except Exception as exc:
                errors.append(f'{venue}:{type(exc).__name__}:{exc}'[:220])
        if best_meta:
            source_meta.append(best_meta)
        accepted.update(best)

    linked = 0
    linked_by_venue = {}
    for e in horse:
        venue = venue_of(e)
        key = (venue, int(e.get('race_no') or 0)) if venue else None
        info = accepted.get(key)
        if not info:
            continue
        _merge_outcomes(e, info.get('outcomes') or [])
        linked += 1
        linked_by_venue[venue] = linked_by_venue.get(venue, 0) + 1

    total = len(horse)
    providers = doc.setdefault('providers', [])
    prior = next((p for p in providers if p.get('provider') == PROVIDER), None)
    prior_detail = dict((prior or {}).get('detail') or {})
    prior_linked = int(prior_detail.get('linked') or 0)

    populated = sum(1 for e in horse if len(e.get('outcomes') or []) >= 2)
    coverage_status = 'PASS' if total and populated == total else ('PARTIAL' if populated else ('NO_TODAY_CARD' if not total else 'UNLINKED'))
    prior_detail.update({
        'status_source': 'STRICT_DATE_RUNNER_FEED_PLUS_DATE_BOUND_FINAL_DETAIL',
        'linked_before_venue_merge': prior_linked,
        'linked_venue_merge': linked,
        'linked': populated,
        'total_events': total,
        'coverage': f'{populated}/{total}',
        'linked_by_venue': linked_by_venue,
        'venue_sources': source_meta,
        'venue_errors': errors[:4],
        'stale_page_policy': 'REJECT',
        'final_detail_repair': {
            'status': repair_status,
            'repaired': repaired,
            'final_events': final_count,
            'stale_outcomes_cleared': cleared,
            'errors': repair_errors[:3],
        },
    })
    providers[:] = [p for p in providers if p.get('provider') != PROVIDER]
    providers.append({'provider': PROVIDER, 'status': coverage_status, 'detail': prior_detail})
    return populated, total, coverage_status
