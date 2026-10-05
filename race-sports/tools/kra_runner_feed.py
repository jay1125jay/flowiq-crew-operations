import time
from kra_official_enricher import RUNNERS_URL, MEET_CODE, fetch, parse_runners, venue_of

PROVIDER = 'HORSE_RUNNERS_KRA'


def _runner_urls(venue):
    meet = MEET_CODE.get(venue)
    if not meet:
        return []
    ts = str(int(time.time()))
    # KRA serves the same runner-card layout by meet. Try the explicit meet
    # selector first, then the menu-qualified variant used by venue pages.
    return [
        f'{RUNNERS_URL}?meet={meet}&_ts={ts}',
        f'{RUNNERS_URL}?Act=02&Sub=1&meet={meet}&_ts={ts}',
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
        best = {}
        best_meta = None
        for url in _runner_urls(venue):
            try:
                raw = fetch(url, timeout=10, retries=1)
                page_date, races = parse_runners(raw)
                matches = 0
                usable = {}
                for e in horse:
                    if venue_of(e) != venue:
                        continue
                    key = (venue, int(e.get('race_no') or 0))
                    info = races.get(key)
                    if not info or not info.get('outcomes'):
                        continue
                    src_time = info.get('start_time')
                    dst_time = e.get('start_time')
                    if src_time and dst_time and src_time != dst_time:
                        continue
                    # When KRA's selected date is stale, exact official schedule
                    # time is the trust signature. This prevents cross-day leakage.
                    if page_date and page_date != today and not (src_time and dst_time and src_time == dst_time):
                        continue
                    usable[key] = info
                    matches += 1
                meta = {
                    'venue': venue,
                    'url': url,
                    'page_date': page_date,
                    'raw_races': len(races),
                    'trusted_races': matches,
                }
                if matches > len(best):
                    best = usable
                    best_meta = meta
                if matches:
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
    status = 'PASS' if total and linked == total else ('PARTIAL' if linked else ('NO_TODAY_CARD' if not total else 'UNLINKED'))
    providers = doc.setdefault('providers', [])
    prior = next((p for p in providers if p.get('provider') == PROVIDER), None)
    prior_detail = dict((prior or {}).get('detail') or {})
    prior_linked = int(prior_detail.get('linked') or 0)

    # Existing KRA enrichment may already have linked one venue. Count actual
    # populated cards after this merge so provider state reflects real coverage.
    populated = sum(1 for e in horse if len(e.get('outcomes') or []) >= 2)
    coverage_status = 'PASS' if total and populated == total else ('PARTIAL' if populated else ('NO_TODAY_CARD' if not total else 'UNLINKED'))
    prior_detail.update({
        'status_source': 'VENUE_SPECIFIC_KRA_RUNNER_FEED',
        'linked_before_venue_merge': prior_linked,
        'linked_venue_merge': linked,
        'linked': populated,
        'total_events': total,
        'coverage': f'{populated}/{total}',
        'linked_by_venue': linked_by_venue,
        'venue_sources': source_meta,
        'venue_errors': errors[:4],
    })
    providers[:] = [p for p in providers if p.get('provider') != PROVIDER]
    providers.append({'provider': PROVIDER, 'status': coverage_status, 'detail': prior_detail})
    return populated, total, coverage_status
