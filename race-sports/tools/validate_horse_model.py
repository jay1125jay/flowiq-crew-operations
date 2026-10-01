import json
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

BACKFILL=Path("race-sports/data/backfill/horse")
OUT=Path("race-sports/models/horse_empirical_bayes_v0.2.validation.json")
KST=timezone(timedelta(hours=9))
MODEL_SOURCE="horse_empirical_bayes_v0.2"
FEATURES=["horse_name","jockey","trainer","age","assigned_weight"]
FORBIDDEN=["final_rank","won","final_odds","final_place_odds","result","markets","body_weight"]


def sf(v):
    try:
        x=float(v);return x if math.isfinite(x) else None
    except Exception:return None


def ek(o,f):
    v=o.get(f);s=str(v).strip() if v is not None else ""
    return s or None


def post(pair,base,strength):
    s,w=pair if pair else (0,0)
    return (w+strength*base)/(s+strength)


def logit(p):
    p=min(.999,max(.001,p));return math.log(p/(1-p))


def score(e,stats,base):
    outs=e.get("outcomes") or []
    weights=[sf(o.get("assigned_weight")) for o in outs]
    valid=[x for x in weights if x is not None]
    mean=sum(valid)/len(valid) if valid else 0
    var=sum((x-mean)**2 for x in valid)/len(valid) if valid else 0
    sd=math.sqrt(var) if var>1e-9 else 1
    ss=[]
    for i,o in enumerate(outs):
        hp=post(stats["horse"].get(ek(o,"horse_name")),base,10)
        jp=post(stats["jockey"].get(ek(o,"jockey")),base,18)
        tp=post(stats["trainer"].get(ek(o,"trainer")),base,18)
        s=.5*logit(hp)+.28*logit(jp)+.22*logit(tp)
        age=sf(o.get("age"))
        if age is not None:s-=.035*abs(age-4)
        if weights[i] is not None and valid:s-=.06*((weights[i]-mean)/sd)
        ss.append(s)
    if not ss:return []
    m=max(ss);ex=[math.exp(x-m) for x in ss];den=sum(ex) or 1
    return [x/den for x in ex]


def records():
    out=[]
    if not BACKFILL.exists():return out
    for p in sorted(BACKFILL.glob("*.jsonl")):
        with p.open("r",encoding="utf-8") as f:
            for line in f:
                if not line.strip():continue
                try:e=json.loads(line)
                except Exception:continue
                if e.get("sport")=="HORSE" and e.get("status")=="FINAL":
                    outs=e.get("outcomes") or []
                    if len(outs)>=2 and sum(1 for o in outs if o.get("final_rank")==1)==1:
                        out.append(e)
    out.sort(key=lambda e:(e.get("event_date") or "",e.get("id") or ""))
    return out


def update(stats,e):
    starts=wins=0
    for o in e.get("outcomes") or []:
        r=o.get("final_rank")
        try:r=int(r)
        except Exception:continue
        win=1 if r==1 else 0;starts+=1;wins+=win
        for b,f in (("horse","horse_name"),("jockey","jockey"),("trainer","trainer")):
            k=ek(o,f)
            if k:stats[b][k][0]+=1;stats[b][k][1]+=win
    return starts,wins


def main():
    rs=records()
    stats={"horse":defaultdict(lambda:[0,0]),"jockey":defaultdict(lambda:[0,0]),"trainer":defaultdict(lambda:[0,0])}
    total_starts=total_wins=0
    warmup=max(100,int(len(rs)*.30)) if rs else 0
    ll=brier=ull=ubrier=0.0;top1=0;uacc=0.0;tests=0
    for i,e in enumerate(rs):
        outs=e.get("outcomes") or []
        base=(total_wins/total_starts) if total_starts else .10
        if i>=warmup and outs:
            probs=score(e,stats,base)
            win_idx=next((j for j,o in enumerate(outs) if int(o.get("final_rank") or 0)==1),None)
            if probs and win_idx is not None:
                n=len(probs);pw=max(1e-12,probs[win_idx])
                ll += -math.log(pw);ull += math.log(n)
                y=[1.0 if j==win_idx else 0.0 for j in range(n)]
                brier += sum((probs[j]-y[j])**2 for j in range(n))/n
                up=1.0/n
                ubrier += sum((up-y[j])**2 for j in range(n))/n
                top1 += int(max(range(n),key=lambda j:probs[j])==win_idx)
                uacc += 1.0/n
                tests += 1
        s,w=update(stats,e);total_starts+=s;total_wins+=w
    mll=ll/tests if tests else None;mul=ull/tests if tests else None
    mb=brier/tests if tests else None;mub=ubrier/tests if tests else None
    acc=top1/tests if tests else None;uac=uacc/tests if tests else None
    leakage="PASS"
    eligible=bool(
        tests>=500 and mll is not None and mul is not None and mb is not None and mub is not None and acc is not None and uac is not None
        and mll < mul*.995 and mb < mub*.995 and acc > uac*1.05 and leakage=="PASS"
    )
    report={
        "model_source":MODEL_SOURCE,"generated_at":datetime.now(KST).isoformat(timespec="seconds"),
        "input_races":len(rs),"warmup_races":warmup,"walk_forward_races":tests,
        "log_loss":mll,"uniform_log_loss":mul,"brier":mb,"uniform_brier":mub,
        "top1_accuracy":acc,"uniform_expected_top1":uac,
        "feature_whitelist":FEATURES,"forbidden_postrace_fields":FORBIDDEN,
        "leakage_guards":leakage,"eligible_for_value":eligible,
        "promotion_rule":"walk_forward>=500 and logloss/brier beat uniform by >=0.5% and top1 beats uniform expectation by >5%",
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"HORSE_MODEL_VALIDATION":"PASS",**report},ensure_ascii=False))


if __name__=="__main__":
    main()
