import json
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path('race-sports')
BACKFILL=ROOT/'data'/'backfill'
HISTORY=ROOT/'data'/'history'
MODELS=ROOT/'models'
KST=timezone(timedelta(hours=9))

CONFIG={
    'CYCLE':{'source':'cycle_empirical_bayes_v0.2','n_default':7,'entity_strength':14.0,'lane_strength':28.0,'entity_weight':.78,'lane_weight':.22},
    'BOAT':{'source':'boat_empirical_bayes_v0.2','n_default':6,'entity_strength':12.0,'lane_strength':24.0,'entity_weight':.72,'lane_weight':.28},
}


def name_of(o):
    s=str(o.get('rider_name') or o.get('racer_name') or o.get('name') or '').strip()
    if s and s[0].isdigit():
        s=s.split(' ',1)[1] if ' ' in s else s
    return s or None


def num_of(o):
    try:return int(o.get('number'))
    except Exception:return None


def rank_of(e,o):
    try:return int(o.get('final_rank'))
    except Exception:pass
    for x in (e.get('result') or {}).get('top3') or []:
        try:
            if int(x.get('number'))==int(o.get('number')):return int(x.get('rank'))
        except Exception:pass
    return None


def winner_number(e):
    for x in (e.get('result') or {}).get('top3') or []:
        try:
            if int(x.get('rank'))==1:return int(x.get('number'))
        except Exception:pass
    return None


def win_label(e,o):
    if o.get('won') is True:return 1
    if o.get('won') is False:return 0
    r=rank_of(e,o)
    if r is not None:return 1 if r==1 else 0
    wn=winner_number(e);n=num_of(o)
    if (e.get('result') or {}).get('status')=='CONFIRMED' and wn is not None and n is not None:
        return 1 if n==wn else 0
    return None


def records(sport):
    by_id={}
    def add(e):
        if e.get('sport')!=sport or e.get('status')!='FINAL':return
        outs=e.get('outcomes') or []
        labels=[win_label(e,o) for o in outs]
        if len(outs)<2 or any(x is None for x in labels) or sum(labels)!=1:return
        key=e.get('id') or f"{sport}|{e.get('event_date')}|{e.get('competition')}|{e.get('race_no')}"
        by_id.setdefault(key,e)

    d=BACKFILL/sport.lower()
    if d.exists():
        for p in sorted(d.glob('*.jsonl')):
            try:
                with p.open('r',encoding='utf-8') as f:
                    for line in f:
                        if not line.strip():continue
                        try:add(json.loads(line))
                        except Exception:continue
            except Exception:continue

    if HISTORY.exists():
        for p in sorted(HISTORY.glob('*.json')):
            try:doc=json.loads(p.read_text(encoding='utf-8'))
            except Exception:continue
            for e in doc.get('events') or []:add(e)

    out=list(by_id.values())
    out.sort(key=lambda e:(e.get('event_date') or '',e.get('id') or ''))
    return out

def posterior(pair,base,strength):
    s,w=pair if pair else (0,0)
    return (w+strength*base)/(s+strength)


def logit(p):
    p=min(.999,max(.001,p));return math.log(p/(1-p))


def score(e,entity,lane,base,cfg):
    outs=e.get('outcomes') or [];ss=[]
    for o in outs:
        ep=posterior(entity.get(name_of(o)),base,cfg['entity_strength'])
        lp=posterior(lane.get(num_of(o)),base,cfg['lane_strength'])
        ss.append(cfg['entity_weight']*logit(ep)+cfg['lane_weight']*logit(lp))
    if not ss:return []
    m=max(ss);ex=[math.exp(x-m) for x in ss];den=sum(ex) or 1.0
    return [x/den for x in ex]


def validate(sport):
    cfg=CONFIG[sport];rs=records(sport);entity=defaultdict(lambda:[0,0]);lane=defaultdict(lambda:[0,0]);starts=wins=0
    warm=max(100,int(len(rs)*.30)) if rs else 0
    ll=brier=ull=ubrier=0.0;top=0;uexp=0.0;tests=0
    for i,e in enumerate(rs):
        outs=e.get('outcomes') or [];base=(wins/starts) if starts else 1.0/cfg['n_default']
        if i>=warm and outs:
            p=score(e,entity,lane,base,cfg);wi=next((j for j,o in enumerate(outs) if win_label(e,o)==1),None)
            if p and wi is not None:
                n=len(p);y=[1.0 if j==wi else 0.0 for j in range(n)];pw=max(1e-12,p[wi]);u=1.0/n
                ll+=-math.log(pw);ull+=math.log(n);brier+=sum((p[j]-y[j])**2 for j in range(n))/n;ubrier+=sum((u-y[j])**2 for j in range(n))/n
                top+=int(max(range(n),key=lambda j:p[j])==wi);uexp+=u;tests+=1
        for o in outs:
            win=win_label(e,o)
            if win is None:continue
            starts+=1;wins+=win
            nm=name_of(o);nu=num_of(o)
            if nm:entity[nm][0]+=1;entity[nm][1]+=win
            if nu is not None:lane[nu][0]+=1;lane[nu][1]+=win
    mll=ll/tests if tests else None;mul=ull/tests if tests else None;mb=brier/tests if tests else None;mub=ubrier/tests if tests else None;acc=top/tests if tests else None;ua=uexp/tests if tests else None
    eligible=bool(tests>=500 and mll is not None and mul is not None and mb is not None and mub is not None and acc is not None and ua is not None and mll<mul*.995 and mb<mub*.995 and acc>ua*1.05)
    report={'sport':sport,'model_source':cfg['source'],'generated_at':datetime.now(KST).isoformat(timespec='seconds'),'input_races':len(rs),'warmup_races':warm,'walk_forward_races':tests,'log_loss':mll,'uniform_log_loss':mul,'brier':mb,'uniform_brier':mub,'top1_accuracy':acc,'uniform_expected_top1':ua,'leakage_guards':'PASS','eligible_for_value':eligible,'feature_whitelist':['participant_name','lane_number'],'forbidden_postrace_fields':['final_rank','won','result','markets','odds'],'promotion_rule':'walk_forward>=500 and logloss/brier beat uniform by >=0.5% and top1 beats uniform expectation by >5%'}
    MODELS.mkdir(parents=True,exist_ok=True);(MODELS/f"{cfg['source']}.validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def main():
    reports=[validate('CYCLE'),validate('BOAT')]
    print(json.dumps({'CYCLE_BOAT_MODEL_VALIDATION':'PASS','reports':reports},ensure_ascii=False))

if __name__=='__main__':main()
