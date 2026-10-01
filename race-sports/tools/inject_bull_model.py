import json
import math
from pathlib import Path

DATA = Path('race-sports/data/today.json')
MODEL = Path('race-sports/models/bull_threeclass_v1.3.0.json')
CLASSES = ['RED', 'DRAW', 'BLUE']


def softmax_map(logits):
    vals = [float(logits[c]) for c in CLASSES]
    m = max(vals)
    es = [math.exp(x - m) for x in vals]
    s = sum(es)
    return {c: es[i] / s for i, c in enumerate(CLASSES)}


def portable_v2_score(raw, spec):
    base = spec.get('baseline') or {}
    logits = {c: float((spec.get('base_logits') or {}).get(c, 0.0) or 0.0) for c in CLASSES}

    for f in spec.get('numeric_features') or []:
        v = raw.get(f)
        if v is None:
            v = base.get(f)
        try:
            x = float(v)
            b = float(base.get(f) or 0.0)
        except Exception:
            continue
        delta = x - b
        slopes = (spec.get('numeric_delta_per_unit') or {}).get(f, {})
        for c in CLASSES:
            logits[c] += delta * float(slopes.get(c, 0.0) or 0.0)

    for f in spec.get('categorical_features') or []:
        v = raw.get(f)
        if v in (None, ''):
            v = base.get(f)
        mapping = (spec.get('categorical_delta') or {}).get(f, {})
        d = mapping.get(str(v), mapping.get('__UNKNOWN__', {}))
        for c in CLASSES:
            logits[c] += float(d.get(c, 0.0) or 0.0)

    return softmax_map(logits)


def old_vector_for_event(event, spec):
    order = spec.get('feature_order') or []
    bf = event.get('bull_features') or {}
    red = bf.get('RED') or {}
    blue = bf.get('BLUE') or {}
    pair = bf.get('pair') or {}
    flat = {}
    for k, v in red.items(): flat['red_' + k] = v
    for k, v in blue.items(): flat['blue_' + k] = v
    for k in set(red) | set(blue):
        rv, bv = red.get(k), blue.get(k)
        try:
            if rv is not None and bv is not None:
                flat['diff_' + k] = float(rv) - float(bv)
        except Exception:
            pass
    flat['grade'] = pair.get('grade')

    med = spec.get('impute_median') or {}
    mean = spec.get('scale_mean') or {}
    scale = spec.get('scale_scale') or {}
    vec = []
    for name in order:
        v = flat.get(name)
        if v is None:
            v = med.get(name)
        if v is None:
            return None
        try: v = float(v)
        except Exception: return None
        mu = float(mean.get(name, 0.0) or 0.0)
        sc = float(scale.get(name, 1.0) or 1.0)
        if sc == 0: sc = 1.0
        vec.append((v - mu) / sc)
    return vec


def old_score(vec, spec):
    coef = spec.get('coef') or {}
    intercept = spec.get('intercept') or {}
    logits = {}
    for cls in CLASSES:
        row = coef.get(cls)
        if not isinstance(row, list) or len(row) != len(vec):
            return None
        logits[cls] = float(intercept.get(cls, 0.0) or 0.0) + sum(float(a) * float(b) for a, b in zip(row, vec))
    return softmax_map(logits)


def score_event(event, spec):
    fmt = spec.get('format')
    if fmt == 'portable_linear_delta_v2':
        raw = event.get('bull_model_features')
        if not isinstance(raw, dict):
            return None, 'MODEL_FEATURES_MISSING'
        missing = [f for f in (spec.get('feature_order') or []) if f not in raw]
        # Missing values are allowed and use the fitted baseline; missing keys indicate parser mismatch.
        if missing:
            return None, 'MODEL_FEATURE_KEYS_MISSING:' + ','.join(missing[:8])
        return portable_v2_score(raw, spec), None

    vec = old_vector_for_event(event, spec)
    if vec is None:
        return None, 'OLD_VECTOR_INCOMPLETE'
    return old_score(vec, spec), None


def main():
    payload = json.loads(DATA.read_text(encoding='utf-8'))
    spec = json.loads(MODEL.read_text(encoding='utf-8'))
    fmt = spec.get('format')
    ready = bool(spec.get('scoring_ready'))
    if fmt == 'portable_linear_delta_v2':
        ready = ready and bool(spec.get('base_logits')) and bool(spec.get('numeric_delta_per_unit')) and bool(spec.get('categorical_delta'))
    else:
        ready = ready and bool(spec.get('feature_order')) and bool(spec.get('coef'))

    linked = 0
    attempted = 0
    failures = []
    if ready:
        for e in payload.get('events', []):
            if e.get('sport') != 'BULL':
                continue
            attempted += 1
            p, err = score_event(e, spec)
            if not p:
                failures.append({'id':e.get('id'),'reason':err})
                continue
            om = {o.get('key'): o for o in e.get('outcomes', [])}
            if list(om) != CLASSES:
                failures.append({'id':e.get('id'),'reason':'OUTCOME_ORDER_MISMATCH'})
                continue
            for cls in CLASSES:
                om[cls]['model_p'] = float(p[cls])
                om[cls]['model_source'] = spec.get('model_name')
                om[cls]['model_version'] = spec.get('version')
            e['bull_model'] = {
                'name': spec.get('model_name'),
                'version': spec.get('version'),
                'selected': spec.get('selected'),
                'validation': spec.get('validation'),
                'format': fmt,
                'current_feature_adapter': 'CPC_CONFIRMED_CARD_OFFICIAL_V130_ADAPTER',
                'current_prior_proxy': 'CARD_CAREER_WDL',
            }
            linked += 1

    providers = [p for p in payload.get('providers', []) if p.get('provider') != 'BULL_MODEL_V130']
    status = 'PASS' if linked else ('ARTIFACT_REQUIRED' if not ready else ('NO_TODAY_CARD' if attempted == 0 else 'FEATURES_INCOMPLETE'))
    providers.append({
        'provider': 'BULL_MODEL_V130',
        'status': status,
        'detail': {
            'model': spec.get('model_name'),
            'version': spec.get('version'),
            'selected': spec.get('selected'),
            'classes': CLASSES,
            'draw_enabled': True,
            'scoring_ready': ready,
            'format': fmt,
            'attempted': attempted,
            'linked': linked,
            'failures': failures[-5:],
            'artifact_state': spec.get('artifact_state'),
            'validation': spec.get('validation'),
            'probability_note': 'validated historical model; current field prior-history state uses confirmed-card career W/D/L proxy until cloud historical state is fully ported',
        },
    })
    payload['providers'] = providers
    DATA.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({'BULL_MODEL': status, 'ready': ready, 'format': fmt, 'attempted': attempted, 'linked': linked, 'failures': len(failures)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
