#!/usr/bin/env python3
"""Keep exactly one current-follow UI loader in BTC FLOW dashboard."""
from pathlib import Path
import re

p = Path(__file__).with_name('dashboard.html')
s = p.read_text(encoding='utf-8')
tag = '<script src="./dashboard-follow.js?v=3"></script><script src="./dashboard-adaptive.js?v=4"></script>'
pattern = r'<script\s+src=["\']\./dashboard-follow\.js(?:\?[^"\']*)?["\']\s*>\s*</script>'

# Remove every legacy/versioned loader, then add one canonical loader.
clean = re.sub(pattern, '', s, flags=re.IGNORECASE)
clean = re.sub(r'<script\s+src=[\"\']\./dashboard-adaptive\.js(?:\?[^\"\']*)?[\"\']\s*>\s*</script>', '', clean, flags=re.IGNORECASE)
if '</body>' not in clean:
    raise SystemExit('FAIL: </body> not found')
clean = clean.replace('</body>', tag + '</body>', 1)

count = len(re.findall(pattern, clean, flags=re.IGNORECASE))
if count != 1:
    raise SystemExit(f'FAIL: dashboard-follow loader count={count}')

if clean != s:
    p.write_text(clean, encoding='utf-8')
    print('DASHBOARD FOLLOW INTEGRATION PASS normalized-to-one')
else:
    print('DASHBOARD FOLLOW INTEGRATION PASS already-canonical')
