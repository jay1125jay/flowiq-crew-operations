#!/usr/bin/env python3
"""Run Adaptive PAPER on the current cohort while preserving raw retired close signals for category PAPER."""
import datetime as dt
import json
from adaptive_meta import ROOT, OUT, advance
from adaptive_feed import current_catalog_feed


def main():
    state=json.loads(OUT.read_text()) if OUT.exists() else {}
    coh=json.loads((ROOT/'trader-discovery/latest.json').read_text())
    raw_feed=json.loads((ROOT/'trader-discovery/current-positions.json').read_text())
    feed=current_catalog_feed(coh,raw_feed)
    market=json.loads((ROOT/'data/adaptive-market.json').read_text())
    rank=json.loads((ROOT/'data/whale-ranking.json').read_text())
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    OUT.write_text(json.dumps(advance(state,coh,feed,now,market,rank),indent=2)+'\n')
    print('ADAPTIVE PAPER PASS current catalog',feed['observed_wallet_count'],'retired close signals excluded',raw_feed.get('retired_wallet_count',0))

if __name__=='__main__':main()
