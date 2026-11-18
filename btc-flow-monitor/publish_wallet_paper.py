"""Publish PAPER observations using per-account optimistic concurrency, never text rebase."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REL = 'btc-flow-monitor/trader-discovery/wallet-paper.json'


def merge_observations(base, candidate, latest):
    for ledger in (base, candidate, latest):
        if ledger.get('paper_only') is not True or ledger.get('real_trading_enabled') is not False:
            raise ValueError('Expected PAPER-only ledger')
    merged = copy.deepcopy(latest)
    applied, conflicts = [], []
    # A selection change is an independent transaction, not part of this merge.
    if set(base['accounts']) != set(candidate['accounts']) or set(base['accounts']) != set(latest['accounts']):
        return merged, applied, ['selection changed']
    for address, updated in candidate['accounts'].items():
        original, current = base['accounts'][address], latest['accounts'][address]
        if updated == original or updated == current:
            continue
        if current != original:
            conflicts.append(address)
            continue
        merged['accounts'][address] = copy.deepcopy(updated)
        applied.append(address)
    if applied:
        cycles = {json.dumps(c, sort_keys=True): c for c in latest.get('cycles', []) + candidate.get('cycles', [])}
        cutoff = (dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=1)).isoformat()
        merged['cycles'] = sorted((c for c in cycles.values() if c['end'] >= cutoff), key=lambda c: c['end'])
        merged['updated_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        merged['observed_count'] = sum(not a.get('error') for a in merged['accounts'].values())
        merged['cloud_publish'] = dict(at=merged['updated_at'], applied=applied, concurrent_accounts=conflicts)
    return merged, applied, conflicts


def main():
    root = Path(__file__).resolve().parent.parent
    path = root / REL
    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], check=True,
                              capture_output=True, text=True, timeout=120).stdout.strip()
    base = json.loads(path.read_text(encoding='utf-8'))
    result = subprocess.run([sys.executable, str(root/'btc-flow-monitor/wallet_paper.py')], timeout=540)
    if result.returncode not in (0, 2):
        result.check_returncode()
    candidate = json.loads(path.read_text(encoding='utf-8'))
    # Retain a diagnostic copy even when every account has concurrent activity.
    diagnostic = Path(os.environ.get('RUNNER_TEMP', str(root))) / 'cash-flow-candidate.json'
    diagnostic.write_text(json.dumps(candidate, indent=2)+'\n', encoding='utf-8')
    git('config', 'user.name', 'github-actions')
    git('config', 'user.email', 'github-actions[bot]@users.noreply.github.com')
    for attempt in range(5):
        git('fetch', '--depth=1', 'origin', 'main')
        # This script runs only in the isolated Actions checkout.
        git('reset', '--hard', 'origin/main')
        latest = json.loads(path.read_text(encoding='utf-8'))
        merged, applied, conflicts = merge_observations(base, candidate, latest)
        print('CLOUD merge: applied', len(applied), 'concurrent', len(conflicts), flush=True)
        if not applied:
            print('No safe account changes to publish; current accounts preserved.', flush=True)
            return
        path.write_text(json.dumps(merged, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        git('add', '--', REL)
        git('commit', '-m', 'data: merge independent whale observations safely')
        try:
            git('push', 'origin', 'HEAD:main')
            for address in applied:
                a = merged['accounts'][address]
                print('PUBLISHED', address, a.get('last_at'), a.get('error'), flush=True)
            return
        except subprocess.CalledProcessError:
            if attempt == 4:
                raise
            time.sleep(2)


if __name__ == '__main__':
    main()
