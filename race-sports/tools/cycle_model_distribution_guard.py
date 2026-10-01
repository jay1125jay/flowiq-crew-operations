import json
from pathlib import Path

DATA = Path('race-sports/data/today.json')


def main():
    payload = json.loads(DATA.read_text(encoding='utf-8'))
    suppressed = 0
    checked = 0
    for e in payload.get('events') or []:
        if e.get('sport') != 'CYCLE' or e.get('status') == 'FINAL':
            continue
        outcomes = e.get('outcomes') or []
        vals = []
        model_rows = []
        for o in outcomes:
            if o.get('model_source') != 'KCYCLE_AI_OFFICIAL' or o.get('model_p') is None:
                continue
            try:
                vals.append(float(o['model_p']))
                model_rows.append(o)
            except Exception:
                pass
        if not vals:
            continue
        checked += 1
        complete = len(vals) == len(outcomes)
        total = sum(vals)
        if complete and 0.97 <= total <= 1.03:
            continue
        for o in outcomes:
            if o.get('model_source') == 'KCYCLE_AI_OFFICIAL':
                o.pop('model_p', None)
                o.pop('model_source', None)
                o.pop('model_updated_at', None)
        e['model_incomplete'] = True
        e['model_incomplete_reason'] = f'KCYCLE_DISTRIBUTION_SUM_{total:.6f}_ROWS_{len(vals)}_OF_{len(outcomes)}'
        e['value_enabled'] = False
        suppressed += 1

    providers = payload.setdefault('providers', [])
    p = next((x for x in providers if x.get('provider') == 'CYCLE_AI_KCYCLE'), None)
    if p is not None:
        detail = p.get('detail') if isinstance(p.get('detail'), dict) else {}
        detail['distribution_guard_checked'] = checked
        detail['distribution_guard_suppressed'] = suppressed
        detail['incomplete_distribution_policy'] = 'SUPPRESS_NO_RENORMALIZATION'
        p['detail'] = detail

    DATA.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({'CYCLE_MODEL_DISTRIBUTION_GUARD':'PASS','checked':checked,'suppressed':suppressed,'policy':'SUPPRESS_NO_RENORMALIZATION'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
