#!/usr/bin/env python3
"""Merge an observed PAPER snapshot onto the freshest remote checkout, without overwriting events."""
import argparse
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / 'trader-discovery/cloud-replay-log.json'
POSITION = ROOT / 'trader-discovery/current-positions.json'
MAX_EVENTS = 2016


def ts(value):
    try:
        return dt.datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return 0


def guard(data, kind):
    if data.get('paper_only') is not True or data.get('real_trading_enabled') is not False:
        raise ValueError(kind + '_NOT_PAPER_ONLY')


def _events(payload):
    guard(payload, 'REPLAY_LOG')
    if payload.get('schema_version') != 1:
        raise ValueError('WRONG_REPLAY_SCHEMA')
    events = {}
    for event in payload.get('events', []):
        t = str(event.get('at') or '')
        name = str(event.get('id') or '')
        price = float(event.get('btc_mid_usd') or 0)
        if not name or name != t or ts(t) <= 0 or not 1000 < price < 1000000:
            raise ValueError('INVALID_REPLAY_EVENT')
        if not isinstance(event.get('wallets'), dict) or not isinstance(event.get('cohort_wallets'), list):
            raise ValueError('INVALID_REPLAY_WALLET_DATA')
        events[name] = event
    return events


def _coverage(events, now):
    stamps = sorted(ts(item['at']) for item in events)
    if not stamps:
        return {'status': 'NO_EVENTS', 'observed_24h': 0, 'expected_24h': 0}
    start = max(stamps[0], now - 24 * 3600)
    newest = stamps[-1]
    recent = [t for t in stamps if start <= t <= now]
    expected = max(1, int((now - start) // 300))
    count = len(recent)
    last_delay = max(0, int(now - newest))
    max_gap = max([b-a for a,b in zip([start]+recent, recent+[now])]) if recent else now-start
    ratio = round(min(100, count/max(1, expected)*100), 1)
    return {
        'status': 'PASS' if ratio >= 90 and last_delay <= 900 and max_gap <= 900 else 'PARTIAL',
        'observed_24h': count,
        'expected_24h': expected,
        'missing_24h_estimate': max(0, expected - count),
        'coverage_pct_24h': ratio,
        'last_snapshot_age_seconds': last_delay,
        'max_gap_seconds_24h': round(max_gap),
    }


def merge(snapshot_log, snapshot_positions, current_log, current_positions, now=None):
    """Mutate in-memory outputs only; callers can test with disposable fixtures."""
    if now is None:
        now = dt.datetime.now(dt.timezone.utc).timestamp()
    guard(snapshot_positions, 'NEW_POSITIONS')
    guard(current_positions, 'STORED_POSITIONS')
    if float(snapshot_positions.get('btc_mid_usd') or 0) <= 1000:
        raise ValueError('INVALID_SOURCE_BTC_PRICE')
    combined = _events(current_log)
    # Preserve all events already written by any concurrent workflow.
    combined.update(_events(snapshot_log))
    ordered = sorted(combined.values(), key=lambda e: ts(e['at']))[-MAX_EVENTS:]
    result = dict(current_log)
    result['events'] = ordered
    result['updated_at'] = ordered[-1]['at'] if ordered else current_log.get('updated_at')
    result['cadence_seconds'] = 300
    result['max_events'] = MAX_EVENTS
    result['capture_health'] = _coverage(ordered, now)
    latest_positions = current_positions
    if ts(snapshot_positions.get('generated_at')) > ts(current_positions.get('generated_at')):
        latest_positions = snapshot_positions
    return result, latest_positions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot-log', required=True)
    parser.add_argument('--snapshot-positions', required=True)
    options = parser.parse_args()
    old_log = json.loads(LOG.read_text(encoding='utf-8'))
    old_positions = json.loads(POSITION.read_text(encoding='utf-8'))
    snapshot_log = json.loads(Path(options.snapshot_log).read_text(encoding='utf-8'))
    snapshot_positions = json.loads(Path(options.snapshot_positions).read_text(encoding='utf-8'))
    result, latest_positions = merge(snapshot_log, snapshot_positions, old_log, old_positions)
    LOG.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if latest_positions is not old_positions:
        POSITION.write_text(json.dumps(latest_positions, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    c = result['capture_health']
    print('REPLAY MERGE PASS', len(result['events']), c['status'], c['coverage_pct_24h'], 'pct / 24h')


if __name__ == '__main__':
    main()
