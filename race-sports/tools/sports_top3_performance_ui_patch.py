#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / 'live.html'
MARKER = 'SPORTS_TOP3_PAPER_ROI_UI_V2'
BASE_MARKER = 'SPORTS_TOP3_PERFORMANCE_UI_V1'

CSS = r'''
/* SPORTS_TOP3_PAPER_ROI_UI_V2 */
.paperRoiBoard{margin:0 0 9px;border:1px solid #4b4328;background:#1b1709;border-radius:11px;padding:9px}.paperRoiHead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:7px}.paperRoiHead b{font-size:11px;color:#fff4cf}.paperRoiHead span{font-size:8px;color:#a99d78}.paperRoiMetrics{display:grid;grid-template-columns:repeat(4,1fr);gap:5px}.paperRoiMetric{border:1px solid #403719;background:#121006;border-radius:8px;padding:7px}.paperRoiMetric small{display:block;font-size:7px;color:#a99d78}.paperRoiMetric b{display:block;margin-top:2px;font-size:11px;color:#fff4cf}.paperRoiPlus{color:#73f1b0!important}.paperRoiMinus{color:#ff9aa1!important}.paperRoiNote{margin-top:6px;font-size:7px;color:#9b906f;line-height:1.4}
'''

JS = r'''
function paperKrw(v){const n=Number(v);if(!Number.isFinite(n))return'—';return `${n>=0?'+':''}${Math.round(n).toLocaleString('ko-KR')}원`}
function renderTop3PaperRoi(){const p=sportsData?.sports_top3?.performance?.summary?.overall?.paper_roi;if(!p)return'';const roi=Number(p.roi),profit=Number(p.net_profit_krw||0),cls=profit>0?'paperRoiPlus':profit<0?'paperRoiMinus':'',roiText=Number.isFinite(roi)?`${roi>=0?'+':''}${(roi*100).toFixed(1)}%`:'—';return `<div class="paperRoiBoard"><div class="paperRoiHead"><b>10만원 고정 가상수익</b><span>PAPER ONLY · 추천 확정 시 배당 고정</span></div><div class="paperRoiMetrics"><div class="paperRoiMetric"><small>배당 잠금 추천</small><b>${p.odds_locked_picks||0}</b></div><div class="paperRoiMetric"><small>정산 완료</small><b>${p.settled||0}</b></div><div class="paperRoiMetric"><small>누적 순수익</small><b class="${cls}">${paperKrw(profit)}</b></div><div class="paperRoiMetric"><small>ROI</small><b class="${cls}">${roiText}</b></div></div><div class="paperRoiNote">정산 투자금 ${(Number(p.total_staked_krw||0)).toLocaleString('ko-KR')}원 · 반환 ${(Number(p.total_return_krw||0)).toLocaleString('ko-KR')}원 · 배당 미연결 ${p.excluded_no_locked_odds||0}건은 수익률에서 제외 · 과거 배당 소급 추정 안 함</div></div>`}
'''


def replace_once(s: str, old: str, new: str, label: str) -> str:
    if old not in s:
        raise RuntimeError('PATCH_ANCHOR_MISSING:' + label)
    return s.replace(old, new, 1)


def patch_text(s: str) -> str:
    if MARKER in s:
        return s
    if BASE_MARKER not in s or 'function renderTop3Performance()' not in s:
        raise RuntimeError('TOP3_PERFORMANCE_BASE_UI_MISSING')
    s = replace_once(s, '@media(max-width:420px)', CSS + '\n@media(max-width:420px)', 'PAPER_ROI_CSS')
    s = replace_once(s, 'function renderTop3Board(){', JS + '\nfunction renderTop3Board(){', 'PAPER_ROI_JS')
    s = replace_once(s, '${renderTop3Performance()}<div class="top3Grid">', '${renderTop3Performance()}${renderTop3PaperRoi()}<div class="top3Grid">', 'PAPER_ROI_RENDER')
    return s


def patch(path: Path = LIVE) -> bool:
    before = path.read_text(encoding='utf-8')
    after = patch_text(before)
    changed = after != before
    if changed:
        path.write_text(after, encoding='utf-8')
    return changed


def self_test():
    s = '''<style>/* SPORTS_TOP3_UI_V1 */\n/* SPORTS_TOP3_PERFORMANCE_UI_V1 */\n@media(max-width:420px)</style><script>function renderTop3Performance(){return ``}\nfunction renderTop3Board(){return `<section>${renderTop3Performance()}<div class="top3Grid">${blocks}</div></section>`}</script>'''
    out = patch_text(s)
    assert MARKER in out
    assert 'function renderTop3PaperRoi()' in out
    assert '${renderTop3PaperRoi()}' in out
    assert patch_text(out) == out
    print('SPORTS_TOP3_PERFORMANCE_UI_SELF_TEST=PASS')


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--self-test',action='store_true'); ap.add_argument('--check',action='store_true'); a=ap.parse_args()
    if a.self_test:
        self_test(); return
    changed=patch()
    txt=LIVE.read_text(encoding='utf-8')
    if a.check:
        for token in [MARKER,'function renderTop3PaperRoi()','${renderTop3PaperRoi()}']:
            if token not in txt: raise SystemExit('SPORTS_TOP3_PERFORMANCE_UI_CHECK_FAIL:'+token)
    print('SPORTS_TOP3_PERFORMANCE_UI_PATCH=' + ('CHANGED' if changed else 'ALREADY_APPLIED'))

if __name__ == '__main__': main()
