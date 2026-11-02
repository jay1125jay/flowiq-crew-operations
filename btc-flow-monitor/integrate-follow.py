#!/usr/bin/env python3
"""Validate the simplified self-contained BTC FLOW dashboard."""
from pathlib import Path

p = Path(__file__).with_name('dashboard.html')
s = p.read_text(encoding='utf-8')
required = [
    '전체 PAPER 자산',
    '지금 따라가는 고래',
    '6개 PAPER 계좌',
    '시스템 상태',
    'id="accountGrid"',
    'id="followList"',
    'id="engineState"',
]
missing = [x for x in required if x not in s]
if missing:
    raise SystemExit('FAIL: simplified dashboard markers missing: ' + ', '.join(missing))
for legacy in ('dashboard-follow.js', 'dashboard-adaptive.js', 'dashboard-category-realtime.js'):
    if legacy in s:
        raise SystemExit('FAIL: legacy dashboard loader still present: ' + legacy)
print('DASHBOARD INTEGRATION PASS simplified self-contained MVP')
