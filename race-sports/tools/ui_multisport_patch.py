from pathlib import Path

P = Path('race-sports/live.html')


def replace_once(s, old, new, label):
    if new in s:
        return s, False
    if old not in s:
        raise SystemExit(f'UI_PATCH_SOURCE_NOT_FOUND:{label}')
    return s.replace(old, new, 1), True


def main():
    s = P.read_text(encoding='utf-8')
    changed = False
    patches = [
        (
            "function preOdds(o){return Number(o.odds)>0&&['KBOAT_FINAL_SINGLE_AUTO','KCYCLE_FINAL_SINGLE_AUTO','KRA_FINAL_SINGLE_AUTO'].includes(o.odds_source)&&o.odds_capture_mode==='PRE_RACE_OFFICIAL'}",
            "function preOdds(o){return Number(o.odds)>0&&['KBOAT_FINAL_SINGLE_AUTO','KCYCLE_FINAL_SINGLE_AUTO','KRA_FINAL_SINGLE_AUTO','CPC_FINAL_SINGLE_AUTO'].includes(o.odds_source)&&o.odds_capture_mode==='PRE_RACE_OFFICIAL'}",
            'preOdds bull source',
        ),
        (
            "function resultBox(e){if(!e.result?.top3)return'';const pods=e.result.top3.map(x=>`<div class=\"pod\"><small>${x.rank}위</small><b>${esc(x.number)}</b><div>${esc(x.name)}</div></div>`).join('');const pays=(e.result.markets||[]).map(x=>`<div class=\"pay\"><small>${esc(x.market)} ${esc(x.winner||'')}</small><b>${esc(x.odds||'-')}배</b></div>`).join('');return `<div class=\"result\"><div class=\"podium\">${pods}</div>${pays?`<div class=\"payouts\">${pays}</div>`:''}</div>`}",
            "function resultBox(e){if(!e.result)return'';const pays=(e.result.markets||[]).map(x=>`<div class=\"pay\"><small>${esc(x.market)} ${esc(x.winner||'')}</small><b>${esc(x.odds||'-')}배</b></div>`).join('');if(e.sport==='BULL'&&e.result.winner){const w=e.result.winner;const sides=e.result.sides||{};return `<div class=\"result\"><div class=\"podium\"><div class=\"pod\"><small>홍</small><b>${esc(sides.RED?.decision||'-')}</b><div>${esc(sides.RED?.name||e.left||'-')}</div></div><div class=\"pod\"><small>공식 결과</small><b>${esc(w.label||w.key)}</b><div>${esc(w.name||'-')}</div></div><div class=\"pod\"><small>청</small><b>${esc(sides.BLUE?.decision||'-')}</b><div>${esc(sides.BLUE?.name||e.right||'-')}</div></div></div>${pays?`<div class=\"payouts\">${pays}</div>`:''}</div>`}if(!e.result.top3)return pays?`<div class=\"result\"><div class=\"payouts\">${pays}</div></div>`:'';const pods=e.result.top3.map(x=>`<div class=\"pod\"><small>${x.rank}위</small><b>${esc(x.number)}</b><div>${esc(x.name)}</div></div>`).join('');return `<div class=\"result\"><div class=\"podium\">${pods}</div>${pays?`<div class=\"payouts\">${pays}</div>`:''}</div>`}",
            'bull result rendering',
        ),
        (
            '<div class="kv"><span>공식 AI</span><span>경정 KBOAT · 경륜 KCYCLE</span></div>',
            '<div class="kv"><span>확률 엔진</span><span>경정 KBOAT 공식 · 경륜 KCYCLE 공식 · 소싸움 검증 3분류</span></div><div class="kv"><span>경마</span><span>KRA 출전표·결과 연결 · 자체 확률모델 검증 대기</span></div>',
            'settings probability sources',
        ),
        (
            "function fresh(e){return !e.stale&&e.data_state!=='STALE_LAST_KNOWN_GOOD'}",
            "function fresh(e){return !e.stale&&e.data_state!=='STALE_LAST_KNOWN_GOOD'}\nfunction providerStatus(name){return (data.providers||[]).find(x=>x.provider===name)?.status||null}\nfunction modelFresh(e){if(!(e.outcomes||[]).some(o=>Number(o.model_p)>0))return true;if(e.sport==='BOAT')return providerStatus('BOAT_AI_KBOAT')==='PASS'&&!e.model_stale;if(e.sport==='CYCLE')return providerStatus('CYCLE_AI_KCYCLE')==='PASS';if(e.sport==='BULL')return providerStatus('BULL_MODEL_V130')==='PASS';return true}",
            'model freshness guard',
        ),
        (
            "const src=t.model_source==='KBOAT_AI_OFFICIAL'?'KBOAT 공식 AI':t.model_source==='KCYCLE_AI_OFFICIAL'?'KCYCLE 공식 AI':t.model_source?.startsWith('bull_threeclass')?'소싸움 3분류 모델':'검증 모델';return `<div class=\"aiPick\"><span><small>${src} · 우승확률 1위${fresh(e)?'':' · 직전 정상값'}</small>",
            "const src=t.model_source==='KBOAT_AI_OFFICIAL'?'KBOAT 공식 AI':t.model_source==='KCYCLE_AI_OFFICIAL'?'KCYCLE 공식 AI':t.model_source?.startsWith('bull_threeclass')?'소싸움 3분류 모델':'검증 모델';return `<div class=\"aiPick\"><span><small>${src} · 우승확률 1위${fresh(e)&&modelFresh(e)?'':' · AI지연 · 직전 정상값'}</small>",
            'ai stale label',
        ),
        (
            "actionable=fresh(e)&&e.status==='SCHEDULED'&&preOdds(o)&&p>0",
            "actionable=fresh(e)&&modelFresh(e)&&e.status==='SCHEDULED'&&preOdds(o)&&p>0",
            'runner model freshness gate',
        ),
        (
            "${!fresh(e)?`<span class=\"staleTag\">지연</span>`:''}",
            "${(!fresh(e)||!modelFresh(e))?`<span class=\"staleTag\">지연</span>`:''}",
            'runner stale tag',
        ),
        (
            "a.filter(e=>fresh(e)&&e.status==='SCHEDULED').forEach",
            "a.filter(e=>fresh(e)&&modelFresh(e)&&e.status==='SCHEDULED').forEach",
            'VALUE model freshness gate',
        ),
        (
            "foot=!fresh(e)?'직전 정상 스냅샷 유지 · 추천 비활성':e.status==='FINAL'?'종료 · 추천 비활성':hasOdds?'경기전 공식 단승배당':'경기전 배당 공개 대기'",
            "foot=!fresh(e)?'직전 정상 스냅샷 유지 · 추천 비활성':!modelFresh(e)?'AI 지연 · 직전 정상확률 유지 · 추천 비활성':e.status==='FINAL'?'종료 · 추천 비활성':hasOdds?'경기전 공식 단승배당':'경기전 배당 공개 대기'",
            'event foot model freshness',
        ),
    ]
    for old, new, label in patches:
        s, c = replace_once(s, old, new, label)
        changed = changed or c
    if changed:
        P.write_text(s, encoding='utf-8')
    print('UI_MULTISPORT_PATCH=' + ('UPDATED' if changed else 'ALREADY_APPLIED'))


if __name__ == '__main__':
    main()
