#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];LIVE=ROOT/'live.html';MARKER='SPORTS_TOP3_PROBABILITY_UI_V1'
CSS=r'''
/* SPORTS_TOP3_PROBABILITY_UI_V1 */
.oosBoard{margin:0 0 9px;border:1px solid #2b405c;background:#09131f;border-radius:11px;padding:9px}.oosHead{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:7px}.oosHead b{font-size:11px;color:#e4efff}.oosHead span{font-size:8px;color:#8295ad}.oosBins{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}.oosBin{border:1px solid #1d3149;background:#07101a;border-radius:8px;padding:6px}.oosBin small{display:block;font-size:7px;color:#8295ad}.oosBin b{display:block;font-size:10px;margin-top:2px;color:#e4efff}.oosBin em{display:block;font-style:normal;font-size:7px;color:#91a8c2;margin-top:2px}.oosNote{margin-top:6px;font-size:7px;line-height:1.4;color:#8295ad}
'''
JS=r'''
function renderOosProbabilityReport(){const r=sportsData?.sports_top3?.oos_probability_report;if(!r?.bins)return'';const keys=[['50_55','50–55%'],['55_60','55–60%'],['60_65','60–65%'],['65_70','65–70%'],['70_75','70–75%'],['75_PLUS','75%+']];const cells=keys.map(([k,l])=>{const x=r.bins[k]||{},hr=Number.isFinite(Number(x.hit_rate))?`${(Number(x.hit_rate)*100).toFixed(1)}%`:'—',wl=Number.isFinite(Number(x.wilson95_lower))?`${(Number(x.wilson95_lower)*100).toFixed(1)}%`:'—';return `<div class="oosBin"><small>모델 ${l}</small><b>${x.evaluated||0}전 · ${hr}</b><em>Wilson 하한 ${wl} · 관측 ${x.observed||0}</em></div>`}).join('');const o=r.overall||{},state=r.interpretation?.state==='HOLD_SAMPLE'?'표본 수집중':'해석 가능';return `<div class="oosBoard"><div class="oosHead"><b>OOS 확률구간 실전 검증</b><span>${state}</span></div><div class="oosBins">${cells}</div><div class="oosNote">TOP3 선정 전 전체 적격 경기 기준 · 실제 종료 결과만 평가 · ${o.evaluated||0}/${o.observed||0}경기 평가 · Wilson 95% 하한은 보수적 신뢰도 지표</div></div>`}
'''
def rep(s,old,new,label):
 if old not in s:raise RuntimeError('PATCH_ANCHOR_MISSING:'+label)
 return s.replace(old,new,1)
def patch_text(s):
 if MARKER in s:return s
 if 'SPORTS_TOP3_PERFORMANCE_UI_V1' not in s:raise RuntimeError('PERFORMANCE_UI_MISSING')
 s=rep(s,'@media(max-width:420px)',CSS+'\n@media(max-width:420px)','CSS')
 s=rep(s,'function renderTop3Performance(){',JS+'\nfunction renderTop3Performance(){','JS')
 s=rep(s,'${renderTop3Performance()}<div class="top3Grid">','${renderOosProbabilityReport()}${renderTop3Performance()}<div class="top3Grid">','RENDER')
 return s
def patch(path=LIVE):
 b=path.read_text(encoding='utf-8');a=patch_text(b);c=a!=b
 if c:path.write_text(a,encoding='utf-8')
 return c
def self_test():
 s='''<style>/* SPORTS_TOP3_PERFORMANCE_UI_V1 */\n@media(max-width:420px)</style><script>function renderTop3Performance(){return''} function x(){return `${renderTop3Performance()}<div class="top3Grid">`}</script>''';o=patch_text(s);assert MARKER in o and 'function renderOosProbabilityReport()' in o and '${renderOosProbabilityReport()}${renderTop3Performance()}' in o and patch_text(o)==o;print('SPORTS_TOP3_PROBABILITY_UI_SELF_TEST=PASS')
def main():
 a=argparse.ArgumentParser();a.add_argument('--self-test',action='store_true');a.add_argument('--check',action='store_true');x=a.parse_args()
 if x.self_test:self_test();return
 c=patch();t=LIVE.read_text(encoding='utf-8')
 if x.check:
  for token in [MARKER,'function renderOosProbabilityReport()','${renderOosProbabilityReport()}${renderTop3Performance()}']:
   if token not in t:raise SystemExit('SPORTS_TOP3_PROBABILITY_UI_CHECK_FAIL:'+token)
 print('SPORTS_TOP3_PROBABILITY_UI_PATCH='+('CHANGED' if c else 'ALREADY_APPLIED'))
if __name__=='__main__':main()
