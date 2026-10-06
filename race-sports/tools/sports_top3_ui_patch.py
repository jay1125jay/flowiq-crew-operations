#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "live.html"
MARKER = "SPORTS_TOP3_UI_V1"

CSS = r'''
/* SPORTS_TOP3_UI_V1 */
.headActions{display:flex;align-items:center;justify-content:flex-end;gap:6px}.refreshBtn{border:1px solid #31506a;background:#0b1d2b;color:#d9ecf8;border-radius:9px;padding:6px 8px;font-size:9px;font-weight:900;white-space:nowrap}.refreshBtn:active{transform:translateY(1px)}.refreshBtn:disabled{opacity:.55;cursor:wait}.top3Board{margin:10px 0 12px;border:1px solid #315a49;background:linear-gradient(145deg,#0d211a,#09151a);border-radius:15px;padding:11px}.top3BoardHead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px}.top3BoardHead b{font-size:14px;color:#dfffea}.top3Lock{font-size:8px;color:#7ff0b7;border:1px solid #326d54;border-radius:999px;padding:4px 7px;white-space:nowrap}.top3Grid{display:grid;gap:8px}.top3Sport{border:1px solid #18382c;background:#081812;border-radius:11px;overflow:hidden}.top3SportHead{display:flex;justify-content:space-between;align-items:center;padding:7px 9px;border-bottom:1px solid #173327;font-size:10px}.top3SportHead b{color:#bff6d7}.top3SportHead span{color:#78968a;font-size:8px}.top3Row{display:grid;grid-template-columns:30px minmax(0,1fr) auto;gap:8px;align-items:center;padding:8px 9px;border-bottom:1px solid #122b20}.top3Row:last-child{border-bottom:0}.top3Rank{width:25px;height:25px;display:grid;place-items:center;border-radius:50%;background:#153b2a;color:#8ff0bc;font-size:10px;font-weight:950}.top3Main{min-width:0}.top3Match{font-size:9px;color:#7f9a8e;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.top3Pick{margin-top:2px;font-size:11px;font-weight:950;color:#edfff5;overflow-wrap:anywhere}.top3Sub{margin-top:2px;font-size:8px;color:#779083;line-height:1.35}.top3Nums{text-align:right;white-space:nowrap}.top3Nums b{display:block;font-size:11px;color:#8ff0bc}.top3Nums small{display:block;margin-top:2px;color:#82988e;font-size:7px}.top3Hit{color:#73f1b0!important}.top3Miss{color:#ff9aa1!important}.top3Empty{padding:12px 9px;color:#738b7f;font-size:9px;text-align:center}
'''

JS = r'''
function top3Rows(sport){const g=sportsData?.sports_top3?.by_sport||{};return Array.isArray(g[sport])?g[sport]:[]}
function top3OutcomeStatus(x){if(x?.evaluation&&typeof x.evaluation.hit==='boolean')return x.evaluation.hit?'✓ 적중':'✕ 미적중';if(x?.status==='FINAL')return'결과확인';if(x?.status==='LIVE')return'진행중';if(x?.status==='CANCELLED')return'취소';if(x?.status==='POSTPONED')return'연기';return x?.confidence||'WATCH'}
function top3Row(x){const ai=Number(x.model_p||0),od=Number(x.odds||0),edge=Number(x.edge),hasEdge=Number.isFinite(edge),ev=Number(x.ev),hasEv=Number.isFinite(ev),evalCls=x?.evaluation?(x.evaluation.hit?' top3Hit':' top3Miss'):'',basis=x.pick_basis==='MARKET_EDGE'?'EDGE 우선':'AI 확률',metric=od>1?`${od.toFixed(2)}배${hasEdge?` · EDGE ${edge>=0?'+':''}${(edge*100).toFixed(1)}%p`:''}`:'배당 미연결',evText=hasEv?` · EV ${ev>=0?'+':''}${(ev*100).toFixed(1)}%`:'';return `<div class="top3Row"><div class="top3Rank">${esc(x.rank||'-')}</div><div class="top3Main"><div class="top3Match">${esc(displayStart(x))} · ${esc(x.competition||'')} · ${esc(x.title||x.event_id)}</div><div class="top3Pick">${esc(x.pick_name||x.pick_key)}</div><div class="top3Sub">${esc(basis)} · ${metric}${evText}</div></div><div class="top3Nums"><b>${ai>0?(ai*100).toFixed(1)+'%':'—'}</b><small class="${evalCls.trim()}">${esc(top3OutcomeStatus(x))}</small></div></div>`}
function renderTop3Board(){if(domain!=='SPORTS'||view!=='TODAY')return'';const keys=sp==='ALL'?SPORTS.filter(([k])=>k!=='ALL').map(([k])=>k):[sp],blocks=keys.map(k=>{const rows=top3Rows(k),label=LABEL[k]||k;return `<div class="top3Sport"><div class="top3SportHead"><b>${esc(label)} TOP 3</b><span>${rows.length}/3 확정</span></div>${rows.length?rows.map(top3Row).join(''):`<div class="top3Empty">현재 확정 가능한 경기 없음</div>`}</div>`}).join(''),state=sportsData?.sports_top3?.selection_state==='LOCKED_FOR_KST_DATE'?'오늘 확정 · 결과까지 유지':'산출 대기';return `<section class="top3Board"><div class="top3BoardHead"><b>SPORTS 종목별 TOP 3</b><span class="top3Lock">${esc(state)}</span></div><div class="top3Grid">${blocks}</div></section>`}
'''


def replace_once(s: str, old: str, new: str, label: str) -> str:
    if old not in s:
        raise RuntimeError(f"PATCH_ANCHOR_MISSING:{label}")
    return s.replace(old, new, 1)


def patch_text(s: str) -> str:
    if MARKER in s:
        return s

    s = replace_once(s, "@media(max-width:420px)", CSS + "\n@media(max-width:420px)", "CSS")

    old_header = '<div class="badge" id="badge">연결중</div></div><div class="domains">'
    new_header = '<div class="headActions"><button class="refreshBtn" id="refreshBtn" type="button">↻ 새로고침</button><div class="badge" id="badge">연결중</div></div></div><div class="domains">'
    s = replace_once(s, old_header, new_header, "HEADER_REFRESH")

    old_const = "const $=id=>document.getElementById(id),tabs=$('tabs'),content=$('content'),badge=$('badge'),notice=$('notice');"
    new_const = "const $=id=>document.getElementById(id),tabs=$('tabs'),content=$('content'),badge=$('badge'),notice=$('notice'),refreshBtn=$('refreshBtn');"
    s = replace_once(s, old_const, new_const, "JS_REFRESH_CONST")

    old_tabs = "renderTabs();\n"
    new_tabs = "renderTabs();\nrefreshBtn?.addEventListener('click',async()=>{if(refreshBtn.disabled)return;const old=refreshBtn.textContent;refreshBtn.disabled=true;refreshBtn.textContent='↻ 갱신중';try{await load()}finally{refreshBtn.textContent=old;refreshBtn.disabled=false}});\n"
    s = replace_once(s, old_tabs, new_tabs, "JS_REFRESH_HANDLER")

    s = replace_once(s, "function render(){", JS + "\nfunction render(){", "TOP3_FUNCTIONS")

    old_today = "if(view==='TODAY'){content.innerHTML=`<div class=\"section\"><h2>오늘 경기</h2>"
    new_today = "if(view==='TODAY'){content.innerHTML=`${domain==='SPORTS'?renderTop3Board():''}<div class=\"section\"><h2>오늘 경기</h2>"
    s = replace_once(s, old_today, new_today, "TOP3_RENDER")

    return s


def patch(path: Path = LIVE) -> bool:
    before = path.read_text(encoding="utf-8")
    after = patch_text(before)
    changed = after != before
    if changed:
        path.write_text(after, encoding="utf-8")
    return changed


def self_test():
    s = '''<style>@media(max-width:420px)</style><div class="badge" id="badge">연결중</div></div><div class="domains"><script>const $=id=>document.getElementById(id),tabs=$('tabs'),content=$('content'),badge=$('badge'),notice=$('notice');\nfunction renderTabs(){}\nrenderTabs();\nfunction render(){if(view==='TODAY'){content.innerHTML=`<div class="section"><h2>오늘 경기</h2>${x}`}}\nasync function load(){}</script>'''
    out = patch_text(s)
    assert MARKER in out
    assert 'id="refreshBtn"' in out
    assert 'function renderTop3Board()' in out
    assert "domain==='SPORTS'?renderTop3Board():''" in out
    assert patch_text(out) == out
    print("SPORTS_TOP3_UI_PATCH_SELF_TEST=PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    changed = patch()
    txt = LIVE.read_text(encoding="utf-8")
    if args.check:
        for token in [MARKER, 'id="refreshBtn"', 'function renderTop3Board()', "domain==='SPORTS'?renderTop3Board():''"]:
            if token not in txt:
                raise SystemExit("SPORTS_TOP3_UI_CHECK_FAIL:" + token)
    print("SPORTS_TOP3_UI_PATCH=" + ("CHANGED" if changed else "ALREADY_APPLIED"))


if __name__ == "__main__":
    main()
