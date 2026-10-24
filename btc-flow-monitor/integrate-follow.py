#!/usr/bin/env python3
"""Keep exactly one current-follow UI loader set in BTC FLOW dashboard."""
from pathlib import Path
import re

p = Path(__file__).with_name('dashboard.html')
s = p.read_text(encoding='utf-8')
tag = '<script src="./dashboard-follow.js?v=3"></script><script src="./dashboard-adaptive.js?v=4"></script><script src="./dashboard-category-realtime.js?v=1"></script>'
patterns = [
    r'<script\s+src=["\']\./dashboard-follow\.js(?:\?[^"\']*)?["\']\s*>\s*</script>',
    r'<script\s+src=["\']\./dashboard-adaptive\.js(?:\?[^"\']*)?["\']\s*>\s*</script>',
    r'<script\s+src=["\']\./dashboard-category-realtime\.js(?:\?[^"\']*)?["\']\s*>\s*</script>',
]

clean = s
for pattern in patterns:
    clean = re.sub(pattern, '', clean, flags=re.IGNORECASE)
if '</body>' not in clean:
    raise SystemExit('FAIL: </body> not found')
clean = clean.replace('</body>', tag + '</body>', 1)

for pattern in patterns:
    count = len(re.findall(pattern, clean, flags=re.IGNORECASE))
    if count != 1:
        raise SystemExit(f'FAIL: dashboard loader count={count}')

if clean != s:
    p.write_text(clean, encoding='utf-8')
    print('DASHBOARD INTEGRATION PASS adaptive + stored-category + pc-realtime-category')
else:
    print('DASHBOARD INTEGRATION PASS already-canonical')
