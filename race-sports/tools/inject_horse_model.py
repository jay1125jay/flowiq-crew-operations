import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA = Path("race-sports/data/today.json")
HISTORY = Path("race-sports/data/history")
BACKFILL = Path("race-sports/data/backfill/horse")
VALIDATION = Path("race-sports/models/horse_empirical_bayes_v0.2.validation.json")
KST = timezone(timedelta(hours=9))
MODEL_SOURCE = "horse_empirical_bayes_v0.2"
PROVIDER = "HORSE_MODEL"

SAFE_FIELDS = ("horse_name","jockey","trainer","age","assigned_weight")
BLOCKED_ODDS_SOURCES = {"KRA_API27_OFFICIAL","KRA_API27_1_OFFICIAL","API27","API27_1"}


def now_text():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def safe_float(v):
    try:
        x=float(v);return x if math.isfinite(x) else None
    except Exception:return None


def entity_key(o,field):
    v=o.get(field)
    s=str(v).strip() if v is not None else ""
    return s or None


def iter_backfill():
    if not BACKFILL.exists():return
    for p in sorted(BACKFILL.glob("*.jsonl")):
        try:
            with p.open("r",encoding="utf-8") as f:
                for line in f:
                    if not line.strip():continue
                    try:e=json.loads(line)
                    except Exception:continue
                    if e.get("sport")=="HORSE" and e.get("status")=="FINAL":yield e
        except Exception:continue


def rank_of(e,o):
    try:return int(o.get("final_rank"))
    except Exception:pass
    for x in (e.get("result") or {}).get("top3") or []:
        try:
            if int(x.get("number"))==int(o.get("number")):return int(x.get("rank"))
        except Exception:pass
    return None


def build_stats():
    stats={"horse":defaultdict(lambda:[0,0]),"jockey":defaultdict(lambda:[0,0]),"trainer":defaultdict(lambda:[0,0])}
    total=0;wins=0;races=0;backfill_ids=set()
    for e in iter_backfill() or []:
        if e.get("id"):backfill_ids.add(e.get("id"))
        labeled=False
        for o in e.get("outcomes") or []:
            r=rank_of(e,o)
            if r is None:continue
            labeled=True;total+=1;win=1 if r==1 else 0;wins+=win
            for bucket,field in (("horse","horse_name"),("jockey","jockey"),("trainer","trainer")):
                k=entity_key(o,field)
                if k:stats[bucket][k][0]+=1;stats[bucket][k][1]+=win
        if labeled:races+=1
    if HISTORY.exists():
        for p in sorted(HISTORY.glob("*.json")):
            try:d=json.loads(p.read_text(encoding="utf-8"))
            except Exception:continue
            for e in d.get("events") or []:
                if e.get("sport")!="HORSE" or e.get("status")!="FINAL":continue
                if e.get("id") and e.get("id") in backfill_ids:continue
                labeled=False
                for o in e.get("outcomes") or []:
                    r=rank_of(e,o)
                    if r is None:continue
                    labeled=True;total+=1;win=1 if r==1 else 0;wins+=win
                    for bucket,field in (("horse","horse_name"),("jockey","jockey"),("trainer","trainer")):
                        k=entity_key(o,field)
                        if k:stats[bucket][k][0]+=1;stats[bucket][k][1]+=win
                if labeled:races+=1
    base=(wins/total) if total else 0.10
    return stats,base,total,races


def posterior(pair,base,strength):
    starts,wins=pair if pair else (0,0)
    return (wins+strength*base)/(starts+strength)


def logit(p):
    p=min(.999,max(.001,p));return math.log(p/(1-p))


def score_race(e,stats,base):
    outcomes=list(e.get("outcomes") or [])
    if not outcomes:return []
    weights=[safe_float(o.get("assigned_weight")) for o in outcomes]
    valid=[x for x in weights if x is not None]
    mean=sum(valid)/len(valid) if valid else 0.0
    var=sum((x-mean)**2 for x in valid)/len(valid) if valid else 0.0
    sd=math.sqrt(var) if var>1e-9 else 1.0
    scores=[]
    for i,o in enumerate(outcomes):
        hp=posterior(stats["horse"].get(entity_key(o,"horse_name")),base,10.0)
        jp=posterior(stats["jockey"].get(entity_key(o,"jockey")),base,18.0)
        tp=posterior(stats["trainer"].get(entity_key(o,"trainer")),base,18.0)
        s=.50*logit(hp)+.28*logit(jp)+.22*logit(tp)
        age=safe_float(o.get("age"))
        if age is not None:s-=.035*abs(age-4.0)
        w=weights[i]
        if w is not None and valid:s-=.06*((w-mean)/sd)
        scores.append(s)
    m=max(scores);ex=[math.exp(x-m) for x in scores];den=sum(ex) or 1.0
    return [x/den for x in ex]


def sanitize_kra_odds(doc):
    blocked=0
    for e in doc.get("events") or []:
        if e.get("sport")!="HORSE":continue
        for o in e.get("outcomes") or []:
            src=str(o.get("odds_source") or "")
            if src in BLOCKED_ODDS_SOURCES or src.startswith("KRA_API27"):
                for k in ("odds","odds_source","odds_capture_mode","odds_observed_at"):o.pop(k,None)
                blocked+=1
        hist=[]
        for snap in e.get("odds_history") or []:
            src=str(snap.get("source") or "")
            if src in BLOCKED_ODDS_SOURCES or src.startswith("KRA_API27"):blocked+=1;continue
            hist.append(snap)
        if hist or "odds_history" in e:e["odds_history"]=hist[-120:]
    for p in doc.get("providers") or []:
        if p.get("provider")=="HORSE_PRE_ODDS_KRA":
            d=p.setdefault("detail",{});d["blocked_non_odds_api27"]=blocked;d["allowed_kra_odds_sources"]=["KRA_API301_OFFICIAL","KRA_API28_OFFICIAL"]
    return blocked


def validation_state():
    try:v=json.loads(VALIDATION.read_text(encoding="utf-8"))
    except Exception:return False,{}
    ok=bool(v.get("eligible_for_value") and v.get("model_source")==MODEL_SOURCE and v.get("leakage_guards")=="PASS")
    return ok,v


def apply(doc):
    blocked=sanitize_kra_odds(doc);stats,base,labeled_runners,labeled_races=build_stats();valid,vr=validation_state();updated=0;horse_events=0
    for e in doc.get("events") or []:
        if e.get("sport")!="HORSE":continue
        horse_events+=1
        if e.get("status")!="SCHEDULED":continue
        probs=score_race(e,stats,base)
        if not probs or len(probs)!=len(e.get("outcomes") or []):continue
        for o,p in zip(e["outcomes"],probs):
            o["model_p"]=round(float(p),8);o["model_source"]=MODEL_SOURCE;o["model_updated_at"]=now_text();o["model_state"]="VALIDATED_WALK_FORWARD" if valid else "PROVISIONAL_UNVALIDATED";o["model_validated"]=valid;updated+=1
        e["model_source"]=MODEL_SOURCE;e["model_state"]="VALIDATED_WALK_FORWARD" if valid else "PROVISIONAL_UNVALIDATED";e["model_validated"]=valid;e["value_enabled"]=bool(valid)
    providers=doc.setdefault("providers",[]);providers[:]=[x for x in providers if x.get("provider")!=PROVIDER]
    providers.append({"provider":PROVIDER,"status":("PASS" if valid and horse_events else "PROVISIONAL" if horse_events else "NO_TODAY_CARD"),"rows":updated,"model_source":MODEL_SOURCE,"model_validated":valid,"model_state":"VALIDATED_WALK_FORWARD" if valid else "PROVISIONAL_UNVALIDATED","value_enabled":bool(valid),"history_labeled_runners":labeled_runners,"history_labeled_races":labeled_races,"validation":vr,"blocked_non_odds_api27":blocked,"updated_at":datetime.now(KST).isoformat(timespec="seconds")})
    return updated,horse_events,labeled_runners,labeled_races,valid,blocked


def self_test():
    stats={"horse":defaultdict(lambda:[0,0]),"jockey":defaultdict(lambda:[0,0]),"trainer":defaultdict(lambda:[0,0])}
    e={"outcomes":[{"horse_name":"A","jockey":"J1","trainer":"T1","age":3,"assigned_weight":54},{"horse_name":"B","jockey":"J2","trainer":"T2","age":5,"assigned_weight":57},{"horse_name":"C","jockey":"J3","trainer":"T3","age":4,"assigned_weight":55}]}
    p=score_race(e,stats,.1);assert len(p)==3 and abs(sum(p)-1)<1e-9
    d={"events":[{"sport":"HORSE","odds_history":[{"source":"KRA_API27_OFFICIAL","odds":{"N1":2.0}}],"outcomes":[{"odds":2.0,"odds_source":"KRA_API27_OFFICIAL"}]}],"providers":[]}
    assert sanitize_kra_odds(d)>=1 and "odds" not in d["events"][0]["outcomes"][0]
    print("HORSE_MODEL_SELF_TEST=PASS")


def main():
    if "--self-test" in sys.argv:self_test();return
    doc=json.loads(DATA.read_text(encoding="utf-8"));updated,horse_events,lr,lrc,valid,blocked=apply(doc);DATA.write_text(json.dumps(doc,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print(f"HORSE_MODEL={'PASS' if valid and horse_events else 'PROVISIONAL' if horse_events else 'NO_TODAY_CARD'}");print(f"HORSE_MODEL_ROWS={updated}");print(f"HORSE_HISTORY_LABELED_RUNNERS={lr}");print(f"HORSE_HISTORY_LABELED_RACES={lrc}");print(f"HORSE_MODEL_VALIDATED={str(valid).upper()}");print(f"HORSE_API27_ODDS_BLOCKED={blocked}")


if __name__=="__main__":main()
