import json
import math
from pathlib import Path

DATA = Path('race-sports/data/today.json')
MODEL = Path('race-sports/models/bull_threeclass_v1.3.0.json')
CLASSES = ['RED', 'DRAW', 'BLUE']


def softmax(xs):
    m = max(xs)
    es = [math.exp(x - m) for x in xs]
    s = sum(es)
    return [x / s for x in es]


def vector_for_event(event, spec):
    order = spec.get('feature_order') or []
    bf = event.get('bull_features') or {}
    red = bf.get('RED') or {}
    blue = bf.get('BLUE') or {}
    pair = bf.get('pair') or {}
    flat = {}
    for k, v in red.items(): flat['red_' + k] = v
    for k, v in blue.items(): flat['blue_' + k] = v
    # Difference features are useful for portable linear models.
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


def score(vec, spec):
    coef = spec.get('coef') or {}
    intercept = spec.get('intercept') or {}
    logits = []
    for cls in CLASSES:
        row = coef.get(cls)
        if not isinstance(row, list) or len(row) != len(vec):
            return None
        z = float(intercept.get(cls, 0.0) or 0.0) + sum(float(a) * float(b) for a, b in zip(row, vec))
        logits.append(z)
    ps = softmax(logits)
    return dict(zip(CLASSES, ps))


def main():
    payload = json.loads(DATA.read_text(encoding='utf-8'))
    spec = json.loads(MODEL.read_text(encoding='utf-8'))
    ready = bool(spec.get('scoring_ready')) and bool(spec.get('feature_order')) and bool(spec.get('coef'))
    linked = 0
    attempted = 0

    if ready:
        for e in payload.get('events', []):
            if e.get('sport') != 'BULL':
                continue
            attempted += 1
            vec = vector_for_event(e, spec)
            if vec is None:
                continue
            p = score(vec, spec)
            if not p:
                continue
            om = {o.get('key'): o for o in e.get('outcomes', [])}
            if list(om) != CLASSES:
                continue
            for cls in CLASSES:
                om[cls]['model_p'] = p[cls]
                om[cls]['model_source'] = spec.get('model_name')
                om[cls]['model_version'] = spec.get('version')
            e['bull_model'] = {
                'name': spec.get('model_name'),
                'version': spec.get('version'),
                'selected': spec.get('selected'),
                'validation': spec.get('validation'),
            }
            linked += 1

    providers = [p for p in payload.get('providers', []) if p.get('provider') != 'BULL_MODEL_V130']
    providers.append({
        'provider': 'BULL_MODEL_V130',
        'status': 'PASS' if linked else ('ARTIFACT_REQUIRED' if not ready else ('NO_TODAY_CARD' if attempted == 0 else 'FEATURES_INCOMPLETE')),
        'detail': {
            'model': spec.get('model_name'),
            'version': spec.get('version'),
            'selected': spec.get('selected'),
            'classes': CLASSES,
            'draw_enabled': True,
            'scoring_ready': ready,
            'attempted': attempted,
            'linked': linked,
            'artifact_state': spec.get('artifact_state'),
            'validation': spec.get('validation'),
        },
    })
    payload['providers'] = providers
    DATA.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({'BULL_MODEL': providers[-1]['status'], 'ready': ready, 'attempted': attempted, 'linked': linked}, ensure_ascii=False))


if __name__ == '__main__':
    main()
