from pathlib import Path

P = Path('race-sports/live.html')


def swap(s, old, new, label):
    if new in s:
        return s, False
    if old not in s:
        raise SystemExit('HORSE_UI_SOURCE_NOT_FOUND:' + label)
    return s.replace(old, new, 1), True


def main():
    s = P.read_text(encoding='utf-8')
    changed = False
    patches = [
        (
            "function modelFresh(e){if(!(e.outcomes||[]).some(o=>Number(o.model_p)>0))return true;if(e.sport==='BOAT')return providerStatus('BOAT_AI_KBOAT')==='PASS'&&!e.model_stale;if(e.sport==='CYCLE')return providerStatus('CYCLE_AI_KCYCLE')==='PASS';if(e.sport==='BULL')return providerStatus('BULL_MODEL_V130')==='PASS';return true}",
            "function modelFresh(e){if(!(e.outcomes||[]).some(o=>Number(o.model_p)>0))return true;if(e.sport==='BOAT')return providerStatus('BOAT_AI_KBOAT')==='PASS'&&!e.model_stale;if(e.sport==='CYCLE')return providerStatus('CYCLE_AI_KCYCLE')==='PASS';if(e.sport==='BULL')return providerStatus('BULL_MODEL_V130')==='PASS';if(e.sport==='HORSE')return ['PROVISIONAL','PASS'].includes(providerStatus('HORSE_MODEL'));return true}\nfunction valueModelReady(e){if(e.sport==='HORSE')return e.model_validated===true&&providerStatus('HORSE_MODEL')==='PASS';return modelFresh(e)}",
            'model state',
        ),
        (
            "const src=t.model_source==='KBOAT_AI_OFFICIAL'?'KBOAT 공식 AI':t.model_source==='KCYCLE_AI_OFFICIAL'?'KCYCLE 공식 AI':t.model_source?.startsWith('bull_threeclass')?'소싸움 3분류 모델':'검증 모델';return `<div class=\"aiPick\"><span><small>${src} · 우승확률 1위${fresh(e)&&modelFresh(e)?'':' · AI지연 · 직전 정상값'}</small>",
            "const src=t.model_source==='KBOAT_AI_OFFICIAL'?'KBOAT 공식 AI':t.model_source==='KCYCLE_AI_OFFICIAL'?'KCYCLE 공식 AI':t.model_source?.startsWith('bull_threeclass')?'소싸움 3분류 모델':t.model_source?.startsWith('horse_empirical_bayes')?'경마 AI MVP':'검증 모델';return `<div class=\"aiPick\"><span><small>${src} · 우승확률 1위${fresh(e)&&modelFresh(e)?'':' · AI지연 · 직전 정상값'}</small>",
            'label',
        ),
        (
            "actionable=fresh(e)&&modelFresh(e)&&e.status==='SCHEDULED'&&preOdds(o)&&p>0",
            "actionable=fresh(e)&&valueModelReady(e)&&e.status==='SCHEDULED'&&preOdds(o)&&p>0",
            'runner value gate',
        ),
        (
            "a.filter(e=>fresh(e)&&modelFresh(e)&&e.status==='SCHEDULED').forEach",
            "a.filter(e=>fresh(e)&&valueModelReady(e)&&e.status==='SCHEDULED').forEach",
            'value list gate',
        ),
        (
            "foot=!fresh(e)?'직전 정상 스냅샷 유지 · 추천 비활성':!modelFresh(e)?'AI 지연 · 직전 정상확률 유지 · 추천 비활성':e.status==='FINAL'?'종료 · 추천 비활성':hasOdds?'경기전 공식 단승배당':'경기전 배당 공개 대기'",
            "foot=!fresh(e)?'직전 정상 스냅샷 유지 · 추천 비활성':!modelFresh(e)?'AI 지연 · 직전 정상확률 유지 · 추천 비활성':e.sport==='HORSE'&&!valueModelReady(e)?'경마 AI MVP 검증 중 · VALUE 비활성':e.status==='FINAL'?'종료 · 추천 비활성':hasOdds?'경기전 공식 단승배당':'경기전 배당 공개 대기'",
            'footer',
        ),
        (
            '<div class="kv"><span>경마</span><span>KRA 출전표·경기전 단승배당·결과·확정배당 연결 · 자체 확률모델 검증 대기</span></div>',
            '<div class="kv"><span>경마</span><span>KRA 공식데이터 · 경마 AI MVP 확률표시 · 검증 중 · VALUE 비활성</span></div>',
            'settings',
        ),
    ]
    for old, new, label in patches:
        s, c = swap(s, old, new, label)
        changed = changed or c
    if 'valueModelReady(e)' not in s or '경마 AI MVP' not in s:
        raise SystemExit('HORSE_UI_SAFETY_VERIFY_FAIL')
    if changed:
        P.write_text(s, encoding='utf-8')
    print('HORSE_UI_SAFETY_PATCH=' + ('UPDATED' if changed else 'ALREADY_APPLIED'))


if __name__ == '__main__':
    main()
