#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, math
from pathlib import Path
from collections import defaultdict

ROOT=Path(__file__).resolve().parents[1]
TODAY=ROOT/"data"/"sports_today.json"
HIST=ROOT/"data"/"sports_history"
MODEL_STATE=ROOT/"data"/"model_state"/"sports_elo_v0.2.validation.json"

SPORTS={"SOCCER","BASEBALL","BASKETBALL","VOLLEYBALL"}
MODEL_NAME="sports_elo_v0.2"
MIN_GAMES_FOR_PREDICTION=50
MIN_VALID_ROWS={"SOCCER":200,"BASEBALL":300,"BASKETBALL":200,"VOLLEYBALL":150}

GRID={
    "SOCCER":{
        "k":[8.0,16.0,24.0,32.0],
        "home_adv":[20.0,40.0,60.0,80.0],
        "scale":[350.0,450.0,550.0],
        "shrink":[0.35,0.5,0.65,0.8,1.0],
    },
    "BASEBALL":{
        "k":[2.0,4.0,8.0,12.0,20.0],
        "home_adv":[0.0,10.0,20.0,30.0,40.0],
        "scale":[350.0,450.0,550.0,650.0],
        "shrink":[0.0,0.15,0.3,0.45,0.6,0.8],
    },
    "BASKETBALL":{
        "k":[12.0,20.0,28.0,36.0],
        "home_adv":[30.0,50.0,70.0,90.0],
        "scale":[300.0,360.0,430.0],
        "shrink":[0.5,0.65,0.8,1.0],
    },
    "VOLLEYBALL":{
        "k":[12.0,20.0,28.0,36.0],
        "home_adv":[20.0,40.0,60.0,80.0],
        "scale":[320.0,400.0,480.0],
        "shrink":[0.5,0.65,0.8,1.0],
    },
}

def logistic(diff:float,scale:float)->float:
    return 1.0/(1.0+10.0**(-diff/scale))

def raw_probs(sport:str,hr:float,ar:float,param:dict)->dict:
    diff=(hr+param["home_adv"])-ar
    q=logistic(diff,param["scale"])
    if sport=="SOCCER":
        draw=max(.16,min(.30,.26*math.exp(-abs(diff)/900.0)))
        return {"HOME":(1-draw)*q,"DRAW":draw,"AWAY":(1-draw)*(1-q)}
    return {"HOME":q,"AWAY":1-q}

def calibrated_probs(sport:str,hr:float,ar:float,param:dict)->dict:
    p=raw_probs(sport,hr,ar,param)
    n=len(p);u=1.0/n;a=float(param["shrink"])
    out={k:a*v+(1-a)*u for k,v in p.items()}
    z=sum(out.values())
    return {k:v/z for k,v in out.items()}

def actual(e:dict):
    r=e.get("result") or {}
    wk=r.get("winner_key")
    if wk in {"HOME","AWAY","DRAW"}: return wk
    try:
        h=float(r["home_score"]);a=float(r["away_score"])
    except Exception:return None
    if h>a:return "HOME"
    if a>h:return "AWAY"
    return "DRAW" if e.get("sport")=="SOCCER" else None

def history_events()->list[dict]:
    rows=[]
    if not HIST.exists():return rows
    for p in sorted(HIST.glob("*.json")):
        try:obj=json.loads(p.read_text(encoding="utf-8"))
        except Exception:continue
        for e in obj.get("events",[]):
            if e.get("sport") in SPORTS and e.get("status")=="FINAL" and actual(e):
                rows.append(e)
    uniq={}
    for e in rows:
        if e.get("id"):uniq[e["id"]]=e
    return sorted(uniq.values(),key=lambda e:(e.get("start_timestamp",0),e.get("id","")))

def candidates(sport:str):
    g=GRID[sport]
    for k in g["k"]:
        for home_adv in g["home_adv"]:
            for scale in g["scale"]:
                for shrink in g["shrink"]:
                    yield {"k":k,"home_adv":home_adv,"scale":scale,"shrink":shrink}

def update_rating(rating, sport:str, h:str, a:str, y:str, param:dict):
    expected=logistic((rating[h]+param["home_adv"])-rating[a],param["scale"])
    score=1.0 if y=="HOME" else 0.0 if y=="AWAY" else 0.5
    delta=param["k"]*(score-expected)
    rating[h]+=delta;rating[a]-=delta

def score_param(rows:list[dict], sport:str, param:dict, start_eval:int, end_eval:int)->tuple[float,int]:
    rating=defaultdict(lambda:1500.0);ll=0.0;n=0
    for i,e in enumerate(rows):
        h=e.get("home");a=e.get("away");y=actual(e)
        if not h or not a or not y:continue
        p=calibrated_probs(sport,rating[h],rating[a],param)
        if start_eval<=i<end_eval:
            py=max(1e-12,min(1-1e-12,p.get(y,1e-12)))
            ll-=math.log(py);n+=1
        update_rating(rating,sport,h,a,y,param)
    return (ll/n if n else float("inf"),n)

def choose_param(rows:list[dict],sport:str)->dict:
    n=len(rows)
    if n<80:
        return next(candidates(sport))
    tune_end=max(70,int(n*0.70))
    tune_start=max(50,int(tune_end*0.35))
    best=None
    for param in candidates(sport):
        ll,count=score_param(rows,sport,param,tune_start,tune_end)
        key=(ll,-count,param["shrink"],param["k"])
        if best is None or key<best[0]:
            best=(key,param)
    return dict(best[1])

def evaluate_holdout(rows:list[dict],sport:str,param:dict)->tuple[dict,dict]:
    n=len(rows);holdout_start=max(50,int(n*0.70))
    rating=defaultdict(lambda:1500.0)
    correct=0;ll=0.0;brier=0.0;count=0
    for i,e in enumerate(rows):
        h=e.get("home");a=e.get("away");y=actual(e)
        if not h or not a or not y:continue
        p=calibrated_probs(sport,rating[h],rating[a],param)
        if i>=holdout_start:
            pred=max(p,key=p.get);correct+=pred==y
            py=max(1e-12,min(1-1e-12,p.get(y,1e-12)))
            ll-=math.log(py)
            brier+=sum((p[k]-(1.0 if k==y else 0.0))**2 for k in p)/len(p)
            count+=1
        update_rating(rating,sport,h,a,y,param)
    classes=3 if sport=="SOCCER" else 2
    uniform=math.log(classes)
    avg_ll=ll/count if count else None
    margin=(uniform-avg_ll) if avg_ll is not None else None
    min_rows=MIN_VALID_ROWS[sport]
    validated=bool(count>=min_rows and avg_ll is not None and avg_ll<uniform)
    val={
        "games":n,"holdout_rows":count,"walk_forward_rows":count,
        "accuracy":round(correct/count,6) if count else None,
        "log_loss":round(avg_ll,6) if avg_ll is not None else None,
        "brier":round(brier/count,6) if count else None,
        "uniform_log_loss":round(uniform,6),
        "log_loss_edge":round(margin,6) if margin is not None else None,
        "validated":validated,
        "selected_params":param,
        "validation_contract":"CHRONOLOGICAL_70_30_HOLDOUT_NO_FUTURE_LEAKAGE",
    }
    return rating,val

def fit_all(rows:list[dict],sport:str,param:dict):
    rating=defaultdict(lambda:1500.0)
    for e in rows:
        h=e.get("home");a=e.get("away");y=actual(e)
        if not h or not a or not y:continue
        update_rating(rating,sport,h,a,y,param)
    return rating

def train(rows:list[dict]):
    by={s:[] for s in SPORTS}
    for e in rows:
        if e.get("sport") in by:by[e["sport"]].append(e)
    ratings={};validation={};params={}
    for s in SPORTS:
        sr=by[s]
        if len(sr)<MIN_GAMES_FOR_PREDICTION:
            validation[s]={
                "games":len(sr),"holdout_rows":0,"walk_forward_rows":0,
                "validated":False,"validation_contract":"INSUFFICIENT_HISTORY"
            }
            params[s]=next(candidates(s))
            ratings[s]=fit_all(sr,s,params[s])
            continue
        param=choose_param(sr,s);params[s]=param
        _,val=evaluate_holdout(sr,s,param)
        ratings[s]=fit_all(sr,s,param);validation[s]=val
    return ratings,validation,params

def inject():
    p=json.loads(TODAY.read_text(encoding="utf-8"))
    rows=history_events()
    rating,val,params=train(rows)
    for e in p.get("events",[]):
        s=e.get("sport")
        if s not in SPORTS:continue
        h=e.get("home");a=e.get("away")
        if not h or not a:continue
        games=int(val.get(s,{}).get("games",0))
        e["model_source"]=MODEL_NAME
        e["model_validated"]=bool(val.get(s,{}).get("validated"))
        e["value_enabled"]=False
        if games<MIN_GAMES_FOR_PREDICTION:
            e["model_state"]="INSUFFICIENT_HISTORY"
            for o in e.get("outcomes",[]):
                o.pop("model_p",None)
                o["model_source"]=MODEL_NAME
                o["model_state"]="INSUFFICIENT_HISTORY"
            continue
        dist=calibrated_probs(s,rating[s][h],rating[s][a],params[s])
        state="VALIDATED_HOLDOUT" if val.get(s,{}).get("validated") else "PROVISIONAL_ELO_UNVALIDATED"
        e["model_state"]=state
        for o in e.get("outcomes",[]):
            if o.get("key") in dist:
                o["model_p"]=dist[o["key"]]
                o["model_source"]=MODEL_NAME
                o["model_state"]=state
    TODAY.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding="utf-8")
    MODEL_STATE.parent.mkdir(parents=True,exist_ok=True)
    state={
        "model":MODEL_NAME,
        "validation":val,
        "history_events":len(rows),
        "safety":{"value_enabled":False,"market_odds_required_before_value":True}
    }
    MODEL_STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"SPORTS_MODEL_INJECT":"PASS","model":MODEL_NAME,"history_events":len(rows),"validation":val},ensure_ascii=False))

def self_test():
    rows=[];ts=1
    for i in range(900):
        home="A" if i%2==0 else "B";away="B" if i%2==0 else "A"
        winner="HOME" if home=="A" else "AWAY"
        rows.append({"id":f"x{i}","sport":"BASKETBALL","home":home,"away":away,"status":"FINAL",
                     "start_timestamp":ts+i,"result":{"winner_key":winner,"home_score":100 if winner=="HOME" else 90,"away_score":90 if winner=="HOME" else 100}})
    r,v,p=train(rows)
    assert v["BASKETBALL"]["holdout_rows"]>=200
    assert v["BASKETBALL"]["validated"] is True
    q=calibrated_probs("SOCCER",1500,1500,{"k":20.0,"home_adv":50.0,"scale":450.0,"shrink":0.8})
    assert abs(sum(q.values())-1)<1e-9 and "DRAW" in q
    assert p["BASKETBALL"]["shrink"]>=0
    print(json.dumps({"SPORTS_MODEL_SELF_TEST":"PASS","model":MODEL_NAME},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");a=ap.parse_args()
    if a.self_test:return self_test()
    inject()

if __name__=="__main__":
    main()
