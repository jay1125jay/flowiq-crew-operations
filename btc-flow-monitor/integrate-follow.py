#!/usr/bin/env python3
"""Safely inject current-follow UI loader into BTC FLOW dashboard. Idempotent."""
from pathlib import Path
p=Path(__file__).with_name('dashboard.html')
s=p.read_text(encoding='utf-8')
tag='<script src="./dashboard-follow.js?v=2"></script>'
if tag in s:
    print('DASHBOARD FOLLOW INTEGRATION PASS already-present')
else:
    if '</body>' not in s: raise SystemExit('FAIL: </body> not found')
    s=s.replace('</body>',tag+'</body>',1)
    p.write_text(s,encoding='utf-8')
    print('DASHBOARD FOLLOW INTEGRATION PASS injected')
