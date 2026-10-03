#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math
from pathlib import Path
from collections import defaultdict
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
TODAY=ROOT/"data"/"sports_today.json"
HIST=ROOT/"data"/"sports_history"
MODEL_STATE=ROOT/"data"/"model_state"/"sports_elo_v0.1.validation.json"
SPORTS={"SOCCER","BASEBALL","BASKETBALL","VOLLEYBALL"}
K={"SOCCER":24.0,"BASEBALL":20.0,"BASKETBALL":28.0,"VOLLEYBALL":26.0}
HOME_ADV={"SOCCER":55.0,"BASEBALL":35.0,"BASKETBALL":60.0,"VOLLEYBALL":45.0}
SCALE={"SOCCER":400.0,"BASEBALL":400.0,"BASKETBALL":360.0,"VOLLEYBALL":380.0}

def logistic(diff,scale):
    return 1.0/(1.0+10.0**(-diff/scale))

def probs(sport,hr,ar):
    diff=(hr+HOME_ADV[sport])-ar
    q=logistic(diff,SCALE[sport])
    if sport=="SOCCER":
        draw=max(.16,min(.30,.26*math.exp(-abs(diff)/900.0)))
        return {"HOME":(1-draw)*q,"DRAW":draw,"AWAY":(1-draw)*(1-q)}
    return {"HOME":q,"AWAY":1-q}

def actual(e):
    r=e.get("result") or {}
    wk=r.get("winner_key")
    if wk in {"HOME","AWAY","DRAW"}: return wk
    try:
        h=float(r["home_score"]); a=float(r["away_score"])
    except Exception: return None
    if h>a:return "HOME"
    if a>h:return "AWAY"
    return "DRAW" if e.get("sport")=="SOCCER" else None

def history_events():
    rows=[]
    if not HIST.exists(): return rows
    for p in sorted(HIST.glob("*.json")):
        try: obj=json.loads(p.read_text(encoding="utf-8"))
        except Exception: continue
        for e in obj.get("events",[]):
            if e.get("sport") in SPORTS and e.get("status")=="FINAL" and actual(e):
                rows.append(e)
    uniq={}
    for e in rows: uniq[e.get("id")]=e
    return sorted(uniq.values(),key=lambda e:(e.get("start_timestamp",0),e.get("id","")))

def train(rows):
    rating={s:defaultdict(lambda:1500.0) for s in SPORTS}
    games=defaultdict(int); samples=defaultdict(list)
    for e in rows:
        s=e["sport"]; h=e.get("home"); a=e.get("away"); y=actual(e)
        if not h or not a or not y: continue
        p=probs(s,rating[s][h],rating[s][a])
        games[s]+=1
        if games[s]>50:
            samples[s].append((p,y))
        score=1.0 if y=="HOME" else 0.0 if y=="AWAY" else 0.5
        expected=logistic((rating[s][h]+HOME_ADV[s])-rating[s][a],SCALE[s])
        delta=K[s]*(score-expected)
        rating[s][h]+=delta
        rating[s][a]-=delta
    validation={}
    for s in SPORTS:
        ss=samples[s]
        if not ss:
            validation[s]={"games":games[s],"walk_forward_rows":0,"validated":False}
            continue
        correct=0; ll=0.0; brier=0.0
        for p,y in ss:
            pred=max(p,key=p.get)
            correct+=pred==y
            py=max(1e-9,min(1-1e-9,p.get(y,1e-9)))
            ll-=math.log(py)
            keys=list(p)
            brier+=sum((p[k]-(1.0 if k==y else 0.0))**2 for k in keys)/len(keys)
        n=len(ss); classes=3 if s=="SOCCER" else 2
        validation[s]={
            "games":games[s],"walk_forward_rows":n,
            "accuracy":round(correct/n,6),
            "log_loss":round(ll/n,6),
            "brier":round(brier/n,6),
            "uniform_log_loss":round(math.log(classes),6),
            "validated": bool(n>=200 and ll/n < math.log(classes)),
        }
    return rating,validation

def inject():
    p=json.loads(TODAY.read_text(encoding="utf-8"))
    rows=history_events()
    rating,val=train(rows)
    for e in p.get("events",[]):
        s=e.get("sport")
        if s not in SPORTS: continue
        h=e.get("home"); a=e.get("away")
        if not h or not a: continue
        if int(val.get(s,{}).get("games",0)) < 50:
            e["model_source"]="sports_elo_v0.1"
            e["model_state"]="INSUFFICIENT_HISTORY"
            e["model_validated"]=False
            e["value_enabled"]=False
            continue
        dist=probs(s,rating[s][h],rating[s][a])
        for o in e.get("outcomes",[]):
            if o.get("key") in dist:
                o["model_p"]=dist[o["key"]]
                o["model_source"]="sports_elo_v0.1"
                o["model_state"]="VALIDATED_WALK_FORWARD" if val.get(s,{}).get("validated") else "PROVISIONAL_ELO_UNVALIDATED"
        e["model_source"]="sports_elo_v0.1"
        e["model_validated"]=bool(val.get(s,{}).get("validated"))
        e["value_enabled"]=False
    TODAY.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding="utf-8")
    MODEL_STATE.parent.mkdir(parents=True,exist_ok=True)
    state={"model":"sports_elo_v0.1","validation":val,"history_events":len(rows)}
    MODEL_STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"SPORTS_MODEL_INJECT":"PASS","history_events":len(rows),"validation":val},ensure_ascii=False))

def self_test():
    rows=[]
    ts=1
    for i in range(260):
        rows.append({"id":f"x{i}","sport":"BASKETBALL","home":"A" if i%2==0 else "B","away":"B" if i%2==0 else "A","status":"FINAL","start_timestamp":ts+i,"result":{"winner_key":"HOME","home_score":100,"away_score":90}})
    _,v=train(rows)
    assert v["BASKETBALL"]["walk_forward_rows"]>=200
    p=probs("SOCCER",1500,1500)
    assert abs(sum(p.values())-1)<1e-9 and "DRAW" in p
    print(json.dumps({"SPORTS_MODEL_SELF_TEST":"PASS"},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--self-test",action="store_true"); a=ap.parse_args()
    if a.self_test:return self_test()
    inject()
if __name__=="__main__":main()
