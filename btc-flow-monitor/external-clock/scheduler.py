#!/usr/bin/env python3
"""Single-shot external clock for the existing BTC PAPER workflow. No trading API."""
import datetime as dt
import json
import os
import sys
import urllib.request
import urllib.error

REPO='jay1125jay/flowiq-crew-operations'
WORKFLOW='btc-whale-skill-screen.yml'
BASE='https://api.github.com/repos/'+REPO+'/actions/workflows/'+WORKFLOW
ACTIVE={'queued','in_progress','waiting','pending','requested'}

def decision(runs, now):
    for run in runs:
        created=dt.datetime.fromisoformat(run['created_at'].replace('Z','+00:00'))
        if created.tzinfo is None:
            raise ValueError('timestamp timezone missing')
        age=(now-created).total_seconds()
        if age < -60:
            raise ValueError('future run timestamp')
        if run['status'] in ACTIVE:
            if age > 1200:
                raise ValueError('BTC workflow stuck; inspect GitHub, no duplicate dispatch')
            return 'SKIP_ACTIVE'
        if run['status'] != 'completed':
            raise ValueError('unknown run status')
    if any((now-dt.datetime.fromisoformat(r['created_at'].replace('Z','+00:00'))).total_seconds() < 240 for r in runs):
        return 'SKIP_RECENT'
    return 'DISPATCH'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect rejected')

def request(token, suffix, payload=None):
    req=urllib.request.Request(BASE+suffix,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                 'Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28',
                 'User-Agent':'BTC-Flow-External-Clock'},
        method='GET' if payload is None else 'POST')
    with urllib.request.build_opener(NoRedirect).open(req,timeout=20) as res:
        body=res.read()
        if payload is not None:
            if res.status not in (200,201,204):
                raise ValueError('dispatch not accepted')
            return {'accepted':True}
        return json.loads(body)

def main():
    # Deployment is inert until explicitly enabled after secret configuration.
    if os.getenv('BTC_SCHEDULER_ENABLED','false').lower() != 'true':
        print('DISABLED: BTC_SCHEDULER_ENABLED is not true')
        return 0
    if os.getenv('PAPER_ONLY','').lower() != 'true' or os.getenv('REAL_TRADING','').lower() != 'false':
        print('BLOCKED: explicit PAPER_ONLY=true and REAL_TRADING=false required')
        return 1
    token=os.getenv('BTC_GITHUB_TOKEN','').strip()
    if not token:
        print('BLOCKED: BTC_GITHUB_TOKEN secret missing')
        return 1
    try:
        data=request(token,'/runs?branch=main&per_page=20')
        runs=data['workflow_runs']
        if not isinstance(runs,list):
            raise ValueError('invalid run response')
        result=decision(runs,dt.datetime.now(dt.timezone.utc))
        if result=='DISPATCH':
            # Never retry POST: on timeout acceptance is unknown. Next cron checks runs.
            request(token,'/dispatches',{'ref':'main'})
            print('DISPATCH_ACCEPTED: BTC PAPER workflow; completion not yet verified')
        else:
            print(result)
        return 0
    except urllib.error.HTTPError as e:
        print('GITHUB_HTTP_ERROR status='+str(e.code))
    except Exception as e:
        # Do not print exception bodies, request objects, headers, or credentials.
        print('SCHEDULER_ERROR type='+type(e).__name__)
    return 1

if __name__=='__main__':
    sys.exit(main())
