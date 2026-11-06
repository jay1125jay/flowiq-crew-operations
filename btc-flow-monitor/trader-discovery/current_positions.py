#!/usr/bin/env python3
"""Observe BTC positions in the classified catalog AND previously opened PAPER positions.

Only the real Hyperliquid clearinghouse response can be recorded as FLAT.
A removed/expired ranking entry never manufactures a trader exit. PAPER ONLY.
"""
import datetime as dt
import json
import os
import pathlib
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
COHORT = ROOT / 'trader-discovery' / 'latest.json'
OUT = ROOT / 'trader-discovery' / 'current-positions.json'
CLOUD_PAPER = ROOT / 'trader-discovery' / 'category-paper.json'
API = 'https://api.hyperliquid.xyz/info'


def api(payload):
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json', 'User-Agent': 'BTC-Flow-Paper-Research/3.0'},
        method='POST')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def btc(state):
    for item in state.get('assetPositions', []):
        position = item.get('position', {})
        if position.get('coin') == 'BTC':
            amount = float(position.get('szi') or 0)
            return 'LONG' if amount > 0 else 'SHORT' if amount < 0 else 'FLAT'
    return 'FLAT'


def held_addresses(*files):
    """Read existing live ledger wallets without modifying local/cloud balances."""
    result = set()
    for path in files:
        if not path:
            continue
        filename = pathlib.Path(path)
        if not filename.exists():
            continue
        payload = json.loads(filename.read_text(encoding='utf-8'))
        state = payload.get('state', payload)
        if state.get('paper_only') is not True or state.get('real_trading_enabled') is not False:
            raise ValueError('NON_PAPER_HELD_WALLET_STATE')
        for account in (state.get('accounts') or {}).values():
            result.update((account.get('positions') or {}).keys())
    return result


def build_observations(cohort, previous, extra_held=()):
    if cohort.get('paper_only') is not True or cohort.get('real_trading_enabled'):
        raise ValueError('PAPER_ONLY_REQUIRED')
    rows = cohort.get('wallets') or []
    current = {row.get('address') for row in rows if row.get('address')}
    old_catalog = set((previous or {}).get('catalog_addresses') or ())
    retired = old_catalog - current
    extra = set(extra_held) - current
    observed = {}
    errors = []
    held = {}
    for i, address in enumerate(sorted(current | extra)):
        try:
            value = btc(api({'type': 'clearinghouseState', 'user': address}))
            if address in current:
                observed[address] = value
            else:
                held[address] = value
        except Exception as exc:
            errors.append({'address': address, 'error': type(exc).__name__})
        if i and i % 10 == 0:
            time.sleep(.35)
    # Never put retired addresses into observed as synthetic FLAT.
    price = float(api({'type': 'allMids'})['BTC'])
    if not 1000 < price < 1000000:
        raise ValueError('invalid BTC mid')
    return {
        'schema_version': 2, 'paper_only': True, 'real_trading_enabled': False,
        'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'btc_mid_usd': price, 'catalog_wallet_count': len(current),
        'catalog_addresses': sorted(current), 'retired_wallet_count': len(retired),
        'observed_wallet_count': len(observed), 'held_wallet_count': len(held),
        'errors': errors, 'wallets': observed, 'held_wallets': held,
        'retired_wallet_policy': 'NO_SYNTHETIC_FLAT_TRACK_OPEN_PAPER_POSITIONS',
    }


def main():
    cohort = json.loads(COHORT.read_text(encoding='utf-8'))
    previous = {}
    if OUT.exists():
        previous = json.loads(OUT.read_text(encoding='utf-8'))
    held = held_addresses(CLOUD_PAPER, os.environ.get('BTC_FLOW_PC_CATEGORY_STATE'))
    output = build_observations(cohort, previous, held)
    OUT.write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
    print('FULL POSITION OBSERVATION',
          len(output['wallets']), '/', output['catalog_wallet_count'],
          'held', len(output['held_wallets']),
          'retired', output['retired_wallet_count'],
          'errors', len(output['errors']))
    if output['errors']:
        raise RuntimeError('incomplete position observation')


if __name__ == '__main__':
    main()
