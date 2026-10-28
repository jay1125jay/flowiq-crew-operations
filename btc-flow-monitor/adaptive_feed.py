#!/usr/bin/env python3
"""Build the strict current-catalog feed used by Adaptive validation/execution.

current-positions.json may also contain retired wallets as one-cycle FLAT close
signals for the category PAPER ledgers. Those are intentionally excluded here;
Adaptive requires its observed wallet set to exactly match the current cohort.
"""
import copy


def current_catalog_feed(coh, feed):
    expected = {w.get('address') for w in coh.get('wallets', []) if w.get('address')}
    out = copy.deepcopy(feed)
    raw = feed.get('wallets', {})
    out['wallets'] = {a: raw[a] for a in expected if a in raw}
    out['catalog_addresses'] = sorted(expected)
    out['catalog_wallet_count'] = len(expected)
    out['observed_wallet_count'] = len(out['wallets'])
    return out
