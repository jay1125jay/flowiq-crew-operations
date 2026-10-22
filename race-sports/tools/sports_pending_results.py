"""Bounded read-only recovery of unresolved ESPN picks; never fetch stored URLs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import math
import re
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

KST = timezone(timedelta(hours=9))
ALLOWED = {
    'SOCCER': {'eng.1', 'esp.1', 'ger.1', 'ita.1', 'fra.1', 'uefa.champions',
               'uefa.europa', 'uefa.europa.conf', 'uefa.nations', 'fifa.world',
               'fifa.friendly', 'afc.champions', 'afc.cup', 'afc.asian.cup', 'kor.1'},
    'BASKETBALL': {'nba', 'wnba'}, 'BASEBALL': {'mlb'},
}
SPORT_PATH = {'SOCCER':'soccer', 'BASKETBALL':'basketball', 'BASEBALL':'baseball'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('REDIRECT_REJECTED')


def summary_url(rec):
    # Stored provenance may be untrusted: extract an allowlisted league only,
    # then construct the request from a fixed HTTPS host and numeric event ID.
    sport = rec.get('sport')
    src = urlparse(str(rec.get('source_url') or ''))
    if rec.get('provider') != 'ESPN_PUBLIC' or src.scheme != 'https' or src.netloc != 'site.api.espn.com':
        return None
    prefix = f'/apis/site/v2/sports/{SPORT_PATH.get(sport)}/'
    if not src.path.startswith(prefix):
        return None
    parts = src.path[len(prefix):].split('/')
    if len(parts) != 2 or parts[0] not in ALLOWED.get(sport, set()) or parts[1] != 'scoreboard':
        return None
    eid = str(rec.get('provider_event_id') or '')
    if not re.fullmatch(r'[0-9]{1,14}', eid) or rec.get('event_id') != f'SPORTS-{sport}-{eid}':
        return None
    return f'https://site.api.espn.com/apis/site/v2/sports/{SPORT_PATH[sport]}/{parts[0]}/summary?event={eid}'


def fetch_json(url):
    req = Request(url, headers={'User-Agent':'RaceIQ/1.0 read-only result reconciliation'})
    with build_opener(NoRedirect()).open(req, timeout=8) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('RESPONSE_TOO_LARGE')
    return json.loads(raw)


def normalize_name(value):
    return ' '.join(str(value or '').casefold().split())


def final_event(rec, payload):
    header = payload.get('header') or {}
    eid = str(rec['provider_event_id'])
    if str(header.get('id')) != eid:
        raise ValueError('EVENT_ID_MISMATCH')
    competitions = [c for c in header.get('competitions', []) if str(c.get('id')) == eid]
    if len(competitions) != 1:
        raise ValueError('COMPETITION_ID_MISMATCH')
    c = competitions[0]
    status = (c.get('status') or {}).get('type') or {}
    if status.get('completed') is not True or status.get('state') != 'post':
        return None
    if status.get('name') not in {'STATUS_FINAL', 'STATUS_FULL_TIME'}:
        return None  # Do not guess abandoned/cancelled/shootout settlement rules.
    day = datetime.fromisoformat(c['date'].replace('Z','+00:00')).astimezone(KST).date().isoformat()
    if day != str(rec.get('event_date') or rec.get('date')):
        raise ValueError('EVENT_DATE_MISMATCH')
    scores = {}
    teams = {}
    for side in ('home', 'away'):
        matches = [t for t in c.get('competitors', []) if t.get('homeAway') == side]
        if len(matches) != 1:
            raise ValueError('TEAM_SIDE_MISMATCH')
        team = matches[0].get('team') or {}
        names = {normalize_name(team.get(k)) for k in ('displayName','shortDisplayName','name','location')}
        expected = normalize_name(rec.get(side))
        if not expected or expected not in names:
            raise ValueError('TEAM_IDENTITY_MISMATCH')
        value = float(matches[0]['score'])
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            raise ValueError('INVALID_SCORE')
        scores[side] = int(value)
        teams[side] = str(team.get('id') or '')
    return {'id':rec['event_id'], 'sport':rec['sport'], 'status':'FINAL',
            'event_date':day, 'result':{'home_score':scores['home'], 'away_score':scores['away'],
            'source':'ESPN_EVENT_SUMMARY_RECHECK', 'source_url':summary_url(rec), 'team_ids':teams}}


def recover_pending(records, now=None, fetcher=fetch_json, limit=12):
    now = now or datetime.now(KST)
    candidates = []
    for rec in records.values():
        if isinstance((rec.get('evaluation') or {}).get('hit'), bool):
            continue
        url = summary_url(rec)
        if not url:
            continue
        try:
            start = float(rec.get('start_timestamp'))
            if start > now.timestamp():
                continue
            checked = (rec.get('result_recheck') or {}).get('checked_at')
            if checked and now - datetime.fromisoformat(checked) < timedelta(hours=2):
                continue
        except (TypeError, ValueError):
            continue
        candidates.append((rec, url))
    candidates.sort(key=lambda item: (item[0].get('result_recheck') or {}).get('checked_at',''))
    def probe(item):
        rec, url = item
        try:
            event = final_event(rec, fetcher(url))
            return rec, url, event, 'FINAL_VERIFIED' if event else 'NOT_FINAL'
        except Exception as exc:
            # Persist no response text, credentials, or arbitrary exception URLs.
            reason = str(exc) if isinstance(exc, ValueError) and re.fullmatch('[A-Z_]+',str(exc)) else type(exc).__name__
            return rec, url, None, 'RETRY_' + reason
    recovered = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for rec, url, event, state in pool.map(probe, candidates[:limit]):
            rec['result_recheck'] = {'checked_at':now.isoformat(timespec='seconds'), 'state':state, 'source_url':url}
            if event:
                recovered.append(event)
    return {'date':now.date().isoformat(), 'events':recovered}
