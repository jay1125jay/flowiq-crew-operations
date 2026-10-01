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
            "function preOdds(o){return Number(o.odds)>0&&o.odds_source==='KBOAT_FINAL_SINGLE_AUTO'&&o.odds_capture_mode==='PRE_RACE_OFFICIAL'}",
            "function preOdds(o){return Number(o.odds)>0&&['KBOAT_FINAL_SINGLE_AUTO','KCYCLE_FINAL_SINGLE_AUTO','KRA_FINAL_SINGLE_AUTO'].includes(o.odds_source)&&o.odds_capture_mode==='PRE_RACE_OFFICIAL'}",
            'preOdds multisport',
        ),
        (
            "const src=t.model_source==='KBOAT_AI_OFFICIAL'?'KBOAT 공식 AI':'검증 모델';",
            "const src=t.model_source==='KBOAT_AI_OFFICIAL'?'KBOAT 공식 AI':t.model_source==='KCYCLE_AI_OFFICIAL'?'KCYCLE 공식 AI':t.model_source?.startsWith('bull_threeclass')?'소싸움 3분류 모델':'검증 모델';",
            'AI source label',
        ),
        (
            '<div class="kv"><span>경정 AI</span><span>KBOAT 공식 우승확률</span></div>',
            '<div class="kv"><span>공식 AI</span><span>경정 KBOAT · 경륜 KCYCLE</span></div>',
            'settings AI label',
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
