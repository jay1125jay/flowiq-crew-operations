#!/usr/bin/env python3
"""Run six-category cloud PAPER with performance-ranked TOP 6 selection."""
import datetime
import importlib.util
import json
from pathlib import Path

import category_top6_policy

ROOT = Path(__file__).resolve().parent
CATEGORY_PATH = ROOT / 'trader-discovery' / 'category_paper.py'
OUT = ROOT / 'trader-discovery' / 'category-paper.json'

spec = importlib.util.spec_from_file_location('btcflow_category_paper_cloud', CATEGORY_PATH)
category = importlib.util.module_from_spec(spec)
spec.loader.exec_module(category)
category.SWING_CAPITAL_KRW = 1_000_000
category.SWING_CAPITAL_EPOCH = 'ORIGINAL_1M_10X_V3'


def main():
    state = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
    cohort = json.loads((ROOT / 'trader-discovery' / 'latest.json').read_text(encoding='utf-8'))
    feed = json.loads((ROOT / 'trader-discovery' / 'current-positions.json').read_text(encoding='utf-8'))
    ranked = category_top6_policy.apply_top6_policy(cohort)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state = category_top6_policy.rotate_out_non_top6(state, ranked, feed, now, category)
    state = category.advance(state, ranked, feed, now)
    state['observed_source_at'] = feed['generated_at']
    state['cloud_update_source'] = 'FULL_CLASSIFIED_WHALE_ENGINE'
    state['selection_policy'] = ranked.get('selection_policy')
    state['selection_rankings'] = ranked.get('selection_rankings')
    OUT.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    print('CATEGORY TOP6 PAPER PASS', ranked['selection_policy']['candidate_catalog_count'])


if __name__ == '__main__':
    main()
