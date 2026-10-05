#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]
FILES = (ROOT / 'data' / 'today.json', ROOT / 'data' / 'sports_today.json')
VERSION = 'market_edge_guard_v1.0'
MAX_SNAPSHOT_AGE_MIN = 60


def parse_dt(v):
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        if d.tzinfo is None:
            d = d.replace(tzinfo=KST)
        return d.astimezone(KST)
    except Exception:
        return None


def event_start(e):
    ts = e.get('start_timestamp')
    try:
        if ts is not None:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(KST)
    except Exception:
        pass
    day = str(e.get('event_date') or '')
    tm = str(e.get('start_time') or '')
    if day and len(tm) == 5 and tm[2] == ':':
        try:
            return datetime.fromisoformat(f'{day}T{tm}:00').replace(tzinfo=KST)
        except Exception:
            return None
    return None


def apply_doc(doc, now=None):
    now = now or datetime.now(KST)
    generated = parse_dt(doc.get('generated_at'))
    snapshot_age = (now - generated).total_seconds() / 60 if generated else None
    snapshot_stale = snapshot_age is None or snapshot_age > MAX_SNAPSHOT_AGE_MIN
    suppressed_stale = 0
    suppressed_started = 0

    for e in doc.get('events', []):
        if e.get('status') != 'SCHEDULED':
            continue
        d = e.get('market_decision')
        if not isinstance(d, dict):
            continue
        start = event_start(e)
        started = bool(start and now >= start)
        if snapshot_stale or started:
            reason = 'SNAPSHOT_STALE' if snapshot_stale else 'EVENT_STARTED'
            e['market_decision'] = {
                'version': d.get('version') or 'market_edge_v1.0',
                'guard_version': VERSION,
                'state': reason,
                'primary_type': 'NO_BET',
                'suppressed_prior_type': d.get('primary_type'),
                'snapshot_age_minutes': round(snapshot_age, 1) if snapshot_age is not None else None,
            }
            if snapshot_stale:
                suppressed_stale += 1
            else:
                suppressed_started += 1

    doc['market_edge_guard'] = {
        'version': VERSION,
        'max_snapshot_age_minutes': MAX_SNAPSHOT_AGE_MIN,
        'snapshot_age_minutes': round(snapshot_age, 1) if snapshot_age is not None else None,
        'snapshot_stale': snapshot_stale,
        'suppressed_stale': suppressed_stale,
        'suppressed_started': suppressed_started,
        'checked_at': now.isoformat(timespec='seconds'),
    }
    return suppressed_stale, suppressed_started


def run():
    out = []
    for p in FILES:
        if not p.exists():
            out.append({'file': str(p), 'status': 'MISSING'})
            continue
        doc = json.loads(p.read_text(encoding='utf-8'))
        stale, started = apply_doc(doc)
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
        out.append({'file': str(p), 'status': 'PASS', 'stale': stale, 'started': started})
    print(json.dumps({'MARKET_EDGE_GUARD': 'PASS', 'results': out}, ensure_ascii=False))


def self_test():
    now = datetime(2026, 10, 6, 8, 0, tzinfo=KST)
    stale = {
        'generated_at': '2026-10-06T06:00:00+09:00',
        'events': [{'status': 'SCHEDULED', 'event_date': '2026-10-06', 'start_time': '20:00', 'market_decision': {'primary_type': 'UPSET'}}],
    }
    a, b = apply_doc(stale, now)
    assert a == 1 and b == 0 and stale['events'][0]['market_decision']['state'] == 'SNAPSHOT_STALE'
    started = {
        'generated_at': '2026-10-06T07:50:00+09:00',
        'events': [{'status': 'SCHEDULED', 'event_date': '2026-10-06', 'start_time': '07:30', 'market_decision': {'primary_type': 'VALUE'}}],
    }
    a, b = apply_doc(started, now)
    assert a == 0 and b == 1 and started['events'][0]['market_decision']['state'] == 'EVENT_STARTED'
    print(json.dumps({'MARKET_EDGE_GUARD_SELF_TEST': 'PASS', 'version': VERSION}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        self_test()
    else:
        run()


if __name__ == '__main__':
    main()
