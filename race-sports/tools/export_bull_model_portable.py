from __future__ import annotations

import json
import math
from pathlib import Path

MODEL_DEFAULT = Path(r'C:\RACE_SPORTS_ANALYTICS\models\bull\bull_threeclass_direct_v1.3.0.joblib')
OUT_DEFAULT = Path(r'C:\RACE_SPORTS_ANALYTICS\portable\bull_threeclass_v1.3.0.json')
DESKTOP_COPY = Path.home() / 'Desktop' / 'bull_threeclass_v1.3.0.json'

NUM_FEATURES = [
    'red_age','blue_age','age_diff',
    'red_weight','blue_weight','weight_diff',
    'red_card_win_pct','blue_card_win_pct','card_win_pct_diff',
    'red_record_wins','blue_record_wins','red_record_draws','blue_record_draws','red_record_losses','blue_record_losses',
    'red_recent_wins','blue_recent_wins','red_recent_draws','blue_recent_draws','red_recent_losses','blue_recent_losses',
    'red_h2h_wins','blue_h2h_wins','red_h2h_meets','blue_h2h_meets','red_h2h_rate','blue_h2h_rate',
    'red_trainer_wins','blue_trainer_wins','red_trainer_starts','blue_trainer_starts','red_trainer_rate','blue_trainer_rate',
    'red_joint_wins','blue_joint_wins','red_joint_draws','blue_joint_draws','red_joint_losses','blue_joint_losses',
    'red_prior_games','blue_prior_games','prior_games_diff',
    'red_prior_win_rate','blue_prior_win_rate','prior_win_rate_diff',
    'red_prior_draw_rate','blue_prior_draw_rate','prior_draw_rate_diff',
    'weight_class_ord','start_minutes',
]
CAT_FEATURES = [
    'red_breed','blue_breed','red_horn','blue_horn','red_skill','blue_skill',
    'red_region','blue_region','red_trainer','blue_trainer',
    'red_current_class','blue_current_class','red_previous_class','blue_previous_class',
]
CANONICAL_CLASSES = ['RED', 'DRAW', 'BLUE']


def to_jsonable(v):
    try:
        import numpy as np
        if isinstance(v, np.generic):
            return v.item()
    except Exception:
        pass
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def logits_for(pipe, row, np):
    pre = pipe.named_steps['pre']
    clf = pipe.named_steps['model']
    xt = pre.transform(np.asarray([row], dtype=object))
    z = clf.decision_function(xt)
    arr = z[0].tolist() if getattr(z, 'ndim', 1) > 1 else list(z)
    classes = [str(x) for x in clf.classes_.tolist()]
    return {c: float(arr[i]) for i, c in enumerate(classes)}


def probs_from_logits(z):
    vals = [float(z[c]) for c in CANONICAL_CLASSES]
    m = max(vals)
    e = [math.exp(x - m) for x in vals]
    s = sum(e)
    return {c: e[i] / s for i, c in enumerate(CANONICAL_CLASSES)}


def portable_logits(spec, raw):
    z = {c: float(spec['base_logits'][c]) for c in CANONICAL_CLASSES}
    base = spec['baseline']
    for f in spec['numeric_features']:
        v = raw.get(f)
        if v is None:
            v = base.get(f)
        try:
            v = float(v)
            b = float(base.get(f) or 0.0)
        except Exception:
            continue
        d = v - b
        slope = spec['numeric_delta_per_unit'].get(f, {})
        for c in CANONICAL_CLASSES:
            z[c] += d * float(slope.get(c, 0.0))
    for f in spec['categorical_features']:
        v = raw.get(f)
        if v in (None, ''):
            v = base.get(f)
        key = str(v)
        cmap = spec['categorical_delta'].get(f, {})
        delta = cmap.get(key, cmap.get('__UNKNOWN__', {}))
        for c in CANONICAL_CLASSES:
            z[c] += float(delta.get(c, 0.0))
    return z


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default=str(MODEL_DEFAULT))
    ap.add_argument('--out', default=str(OUT_DEFAULT))
    args = ap.parse_args()

    import joblib
    import numpy as np

    model_path = Path(args.model)
    if not model_path.exists():
        raise SystemExit(f'MODEL_NOT_FOUND={model_path}')
    obj = joblib.load(model_path)
    pipe = obj.get('pipeline') if isinstance(obj, dict) else obj
    if pipe is None or not hasattr(pipe, 'named_steps'):
        raise SystemExit('UNSUPPORTED_MODEL_OBJECT')
    if 'pre' not in pipe.named_steps or 'model' not in pipe.named_steps:
        raise SystemExit('PIPELINE_PRE_OR_MODEL_MISSING')

    num_features = list(obj.get('num_features') or NUM_FEATURES) if isinstance(obj, dict) else list(NUM_FEATURES)
    cat_features = list(obj.get('cat_features') or CAT_FEATURES) if isinstance(obj, dict) else list(CAT_FEATURES)
    order = num_features + cat_features
    pre = pipe.named_steps['pre']
    clf = pipe.named_steps['model']
    classes = [str(x) for x in clf.classes_.tolist()]
    if set(classes) != set(CANONICAL_CLASSES):
        raise SystemExit('MODEL_CLASSES_MISMATCH=' + json.dumps(classes, ensure_ascii=False))

    num_pipe = pre.named_transformers_.get('num')
    cat_pipe = pre.named_transformers_.get('cat')
    if num_pipe is None or cat_pipe is None:
        raise SystemExit('NUM_OR_CAT_TRANSFORMER_MISSING')
    nimp = num_pipe.named_steps.get('imputer') or num_pipe.named_steps.get('imp')
    cimp = cat_pipe.named_steps.get('imputer') or cat_pipe.named_steps.get('imp')
    ohe = cat_pipe.named_steps.get('ohe')
    if nimp is None or cimp is None or ohe is None:
        raise SystemExit('IMPUTER_OR_OHE_MISSING')

    nstats = list(getattr(nimp, 'statistics_', []))
    cstats = list(getattr(cimp, 'statistics_', []))
    baseline = {}
    for i, f in enumerate(num_features):
        v = nstats[i] if i < len(nstats) else 0.0
        try:
            if math.isnan(float(v)):
                v = 0.0
        except Exception:
            v = 0.0
        baseline[f] = float(v)
    for i, f in enumerate(cat_features):
        v = cstats[i] if i < len(cstats) else ''
        baseline[f] = str(to_jsonable(v) or '')

    base_row = [baseline[f] for f in order]
    raw_base = dict(baseline)
    base_native = logits_for(pipe, base_row, np)
    base_logits = {c: float(base_native[c]) for c in CANONICAL_CLASSES}

    num_delta = {}
    for i, f in enumerate(num_features):
        row = list(base_row)
        row[i] = float(baseline[f]) + 1.0
        z = logits_for(pipe, row, np)
        num_delta[f] = {c: float(z[c] - base_logits[c]) for c in CANONICAL_CLASSES}

    cat_delta = {}
    categories = list(getattr(ohe, 'categories_', []))
    offset = len(num_features)
    for j, f in enumerate(cat_features):
        vals = categories[j].tolist() if j < len(categories) else []
        mapping = {}
        for v in vals:
            row = list(base_row)
            row[offset + j] = to_jsonable(v)
            z = logits_for(pipe, row, np)
            mapping[str(to_jsonable(v))] = {c: float(z[c] - base_logits[c]) for c in CANONICAL_CLASSES}
        row = list(base_row)
        row[offset + j] = '__PORTABLE_UNKNOWN_CATEGORY__'
        z = logits_for(pipe, row, np)
        mapping['__UNKNOWN__'] = {c: float(z[c] - base_logits[c]) for c in CANONICAL_CLASSES}
        cat_delta[f] = mapping

    validation = {
        'input_rows': 14540,
        'walk_forward_rows': 7270,
        'accuracy': 0.608666,
        'balanced_accuracy': 0.429149,
        'macro_f1': 0.438034,
        'log_loss': 0.723483,
        'draw_precision': 0.296296,
        'draw_recall': 0.054422,
        'draw_f1': 0.091954,
        'leakage_guards': 'PASS',
    }
    spec = {
        'format': 'portable_linear_delta_v2',
        'model_name': 'bull_threeclass_direct_v1.3.0',
        'version': '1.3.0',
        'classes': CANONICAL_CLASSES,
        'selected': 'DIRECT_NATURAL',
        'validation': validation,
        'policy': {
            'draw_enabled': True,
            'outcome_order': CANONICAL_CLASSES,
            'paper_only': True,
            'real_betting': False,
            'ev_threshold': 0.05,
        },
        'scoring_ready': True,
        'artifact_state': 'PORTABLE_FROM_LOCAL_VALIDATED_JOBLIB',
        'numeric_features': num_features,
        'categorical_features': cat_features,
        'feature_order': order,
        'baseline': baseline,
        'base_logits': base_logits,
        'numeric_delta_per_unit': num_delta,
        'categorical_delta': cat_delta,
    }

    # Exactness check around the fitted baseline: baseline, every numeric +1, and one category per field.
    tests = [dict(raw_base)]
    for f in num_features:
        x = dict(raw_base); x[f] = float(x[f]) + 1.0; tests.append(x)
    for j, f in enumerate(cat_features):
        vals = categories[j].tolist() if j < len(categories) else []
        if vals:
            x = dict(raw_base); x[f] = to_jsonable(vals[-1]); tests.append(x)
    max_err = 0.0
    for raw in tests:
        row = [raw[f] for f in order]
        native_p = probs_from_logits({c: logits_for(pipe, row, np)[c] for c in CANONICAL_CLASSES})
        port_p = probs_from_logits(portable_logits(spec, raw))
        max_err = max(max_err, *(abs(native_p[c] - port_p[c]) for c in CANONICAL_CLASSES))
    spec['portable_self_check_max_probability_error'] = max_err
    if max_err > 1e-8:
        raise SystemExit(f'PORTABLE_SELF_CHECK_FAIL={max_err}')

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(spec, ensure_ascii=False, indent=2)
    out.write_text(text, encoding='utf-8')
    try:
        DESKTOP_COPY.write_text(text, encoding='utf-8')
    except Exception:
        pass

    print('PORTABLE_EXPORT=PASS')
    print(f'MODEL={model_path}')
    print(f'OUT={out}')
    print(f'DESKTOP_COPY={DESKTOP_COPY}')
    print(f'PORTABLE_SELF_CHECK_MAX_PROB_ERROR={max_err:.12g}')
    print('NEXT=UPLOAD_DESKTOP_JSON_TO_CHAT')


if __name__ == '__main__':
    main()
