#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / 'live.html'
MARKER = 'SPORTS_TOP3_PERFORMANCE_UI_V1'

CSS = r'''
/* SPORTS_TOP3_PERFORMANCE_UI_V1 */
.perfBoard{margin:0 0 9px;border:1px solid #284b3d;background:#091b15;border-radius:11px;padding:9px}.perfHead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:7px}.perfHead b{font-size:11px;color:#dfffea}.perfHead span{font-size:8px;color:#78968a}.perfMetrics{display:grid;grid-template-columns:repeat(4,1fr);gap:5px}.perfMetric{border:1px solid #17382b;background:#07140f;border-radius:8px;padding:7px}.perfMetric small{display:block;font-size:7px;color:#78968a}.perfMetric b{display:block;margin-top:2px;font-size:12px;color:#dfffea}.perfSports{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin-top:6px}.perfSport{border:1px solid #17382b;border-radius:8px;padding:6px;text-align:center}.perfSport small{display:block;font-size:7px;color:#78968a}.perfSport b{display:block;margin-top:2px;font-size:10px}.perfRecent{margin-top:7px;border-top:1px solid #173327;padding-top:6px}.perfRecentTitle{font-size:8px;color:#78968a;margin-bottom:4px}.perfRecentRow{display:grid;grid-template-columns:48px minmax(0,1fr) auto;gap:6px;align-items:center;padding:4px 0;font-size:8px;border-bottom:1px solid #11291f}.perfRecentRow:last-child{border-bottom:0}.perfRecentRow b{font-size:9px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.perfHit{color:#73f1b0}.perfMiss{color:#ff9aa1}.perfPending{color:#ffd276}.perfSample{margin-top:6px;font-size:7px;color:#78968a;line-height:1.4}
'''

JS = r'''
function perfPct(v){return Number.isFinite(Number(v))?`${(Number(v)*100).toFixed(1)}%`:'—'}
function perfSportLabel(k){return LABEL[k]||k}
function renderTop3Performance(){const p=sportsData?.sports_top3?.performance;if(!p?.summary)return'';const o=p.summary.overall||{},by=p.summary.by_sport||{},sports=['SOCCER','BASEBALL','BASKETBALL','VOLLEYBALL'];const sm=sports.map(k=>{const x=by[k]||{};return `<div class="perfSport"><small>${esc(perfSportLabel(k))}</small><b>${x.evaluated||0}전 · ${perfPct(x.hit_rate)}</b></div>`}).join('');const recent=(p.recent||[]).slice(0,5).map(r=>{const e=r.evaluation,cls=e?(e.hit?'perfHit':'perfMiss'):'perfPending',st=e?(e.hit?'적중':'미적중'):'대기';return `<div class="perfRecentRow"><span>${esc(r.date||'')}</span><b>${esc(r.pick_name||r.pick_key||'-')} · ${esc(r.title||'')}</b><span class="${cls}">${st}</span></div>`}).join('');const need=p.sample_rule?.min_evaluated_per_sport||30;return `<div class="perfBoard"><div class="perfHead"><b>TOP3 누적 성과</b><span>${esc(p.updated_at||'')}</span></div><div class="perfMetrics"><div class="perfMetric"><small>전체 선택</small><b>${o.picks||0}</b></div><div class="perfMetric"><small>평가 완료</small><b>${o.evaluated||0}</b></div><div class="perfMetric"><small>적중/미적중</small><b>${o.hits||0}/${o.misses||0}</b></div><div class="perfMetric"><small>누적 적중률</small><b>${perfPct(o.hit_rate)}</b></div></div><div class="perfSports">${sm}</div>${recent?`<div class="perfRecent"><div class="perfRecentTitle">최근 추천 결과</div>${recent}</div>`:''}<div class="perfSample">종목별 평가 ${need}경기 전까지 기준 고정 · 표본 확보 후 임계값 검토</div></div>`}
'''


def replace_once(s: str, old: str, new: str, label: str) -> str:
    if old not in s:
        raise RuntimeError('PATCH_ANCHOR_MISSING:' + label)
    return s.replace(old, new, 1)


def patch_text(s: str) -> str:
    if MARKER in s:
        return s
    if 'SPORTS_TOP3_UI_V1' not in s or 'function renderTop3Board()' not in s:
        raise RuntimeError('TOP3_BASE_UI_MISSING')
    s = replace_once(s, '@media(max-width:420px)', CSS + '\n@media(max-width:420px)', 'PERF_CSS')
    s = replace_once(s, 'function renderTop3Board(){', JS + '\nfunction renderTop3Board(){', 'PERF_JS')
    old = '<div class="top3Grid">${blocks}</div></section>`'
    new = '${renderTop3Performance()}<div class="top3Grid">${blocks}</div></section>`'
    s = replace_once(s, old, new, 'PERF_RENDER')
    return s


def patch(path: Path = LIVE) -> bool:
    before = path.read_text(encoding='utf-8')
    after = patch_text(before)
    changed = after != before
    if changed:
        path.write_text(after, encoding='utf-8')
    return changed


def self_test():
    s = '''<style>/* SPORTS_TOP3_UI_V1 */\n@media(max-width:420px)</style><script>function renderTop3Board(){return `<section><div class="top3Grid">${blocks}</div></section>`}</script>'''
    out = patch_text(s)
    assert MARKER in out
    assert 'function renderTop3Performance()' in out
    assert '${renderTop3Performance()}' in out
    assert patch_text(out) == out
    print('SPORTS_TOP3_PERFORMANCE_UI_SELF_TEST=PASS')


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--self-test',action='store_true'); ap.add_argument('--check',action='store_true'); a=ap.parse_args()
    if a.self_test:
        self_test(); return
    changed=patch()
    txt=LIVE.read_text(encoding='utf-8')
    if a.check:
        for token in [MARKER,'function renderTop3Performance()','${renderTop3Performance()}']:
            if token not in txt: raise SystemExit('SPORTS_TOP3_PERFORMANCE_UI_CHECK_FAIL:'+token)
    print('SPORTS_TOP3_PERFORMANCE_UI_PATCH=' + ('CHANGED' if changed else 'ALREADY_APPLIED'))

if __name__ == '__main__': main()
