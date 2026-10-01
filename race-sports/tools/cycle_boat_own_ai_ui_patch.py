from pathlib import Path

P = Path('race-sports/live.html')


def replace_if_needed(s, old, new):
    if new in s:
        return s, False
    if old in s:
        return s.replace(old, new, 1), True
    return s, False


def main():
    s = P.read_text(encoding='utf-8')
    changed = False

    patches = [
        (
            "function modelFresh(e){if(!(e.outcomes||[]).some(o=>Number(o.model_p)>0))return true;if(e.sport==='BOAT')return providerStatus('BOAT_AI_KBOAT')==='PASS'&&!e.model_stale;if(e.sport==='CYCLE')return providerStatus('CYCLE_AI_KCYCLE')==='PASS';if(e.sport==='BULL')return providerStatus('BULL_MODEL_V130')==='PASS';if(e.sport==='HORSE')return ['PROVISIONAL','PASS'].includes(providerStatus('HORSE_MODEL'));return true}",
            "function modelFresh(e){if(!(e.outcomes||[]).some(o=>Number(o.model_p)>0))return true;if(e.sport==='BOAT'&&String(e.model_source||'').startsWith('boat_empirical_bayes'))return ['PROVISIONAL','PASS'].includes(providerStatus('BOAT_OWN_MODEL'));if(e.sport==='CYCLE'&&String(e.model_source||'').startsWith('cycle_empirical_bayes'))return ['PROVISIONAL','PASS'].includes(providerStatus('CYCLE_OWN_MODEL'));if(e.sport==='BOAT')return providerStatus('BOAT_AI_KBOAT')==='PASS'&&!e.model_stale;if(e.sport==='CYCLE')return providerStatus('CYCLE_AI_KCYCLE')==='PASS';if(e.sport==='BULL')return providerStatus('BULL_MODEL_V130')==='PASS';if(e.sport==='HORSE')return ['PROVISIONAL','PASS'].includes(providerStatus('HORSE_MODEL'));return true}",
        ),
        (
            "function valueModelReady(e){if(e.sport==='HORSE')return e.model_validated===true&&providerStatus('HORSE_MODEL')==='PASS';return modelFresh(e)}",
            "function valueModelReady(e){if(e.sport==='HORSE')return e.model_validated===true&&providerStatus('HORSE_MODEL')==='PASS';if(e.sport==='CYCLE'&&String(e.model_source||'').startsWith('cycle_empirical_bayes'))return e.model_validated===true&&providerStatus('CYCLE_OWN_MODEL')==='PASS';if(e.sport==='BOAT'&&String(e.model_source||'').startsWith('boat_empirical_bayes'))return e.model_validated===true&&providerStatus('BOAT_OWN_MODEL')==='PASS';return modelFresh(e)}",
        ),
        (
            "const src=t.model_source==='KBOAT_AI_OFFICIAL'?'KBOAT 공식 AI':t.model_source==='KCYCLE_AI_OFFICIAL'?'KCYCLE 공식 AI':t.model_source?.startsWith('bull_threeclass')?'소싸움 3분류 모델':t.model_source?.startsWith('horse_empirical_bayes')?'경마 AI MVP':'검증 모델';",
            "const src=t.model_source?.startsWith('boat_empirical_bayes')?'경정 자체 AI MVP':t.model_source?.startsWith('cycle_empirical_bayes')?'경륜 자체 AI MVP':t.model_source==='KBOAT_AI_OFFICIAL'?'KBOAT 공식 AI':t.model_source==='KCYCLE_AI_OFFICIAL'?'KCYCLE 공식 AI':t.model_source?.startsWith('bull_threeclass')?'소싸움 3분류 모델':t.model_source?.startsWith('horse_empirical_bayes')?'경마 AI MVP':'검증 모델';",
        ),
        (
            '<div class="kv"><span>확률 엔진</span><span>경정 KBOAT 공식 · 경륜 KCYCLE 공식 · 소싸움 검증 3분류</span></div>',
            '<div class="kv"><span>확률 엔진</span><span>경마·경륜·경정 자체 AI MVP · 소싸움 검증 3분류</span></div><div class="kv"><span>공식 AI 비교</span><span>KCYCLE · KBOAT 공식 확률은 별도 보존</span></div>',
        ),
    ]

    for old, new in patches:
        s, c = replace_if_needed(s, old, new)
        changed = changed or c

    if 'CYCLE_OWN_MODEL' not in s or 'BOAT_OWN_MODEL' not in s:
        raise SystemExit('OWN_AI_UI_PATCH_INCOMPLETE')

    if changed:
        P.write_text(s, encoding='utf-8')
    print('CYCLE_BOAT_OWN_AI_UI_PATCH=' + ('UPDATED' if changed else 'ALREADY_APPLIED'))


if __name__ == '__main__':
    main()
