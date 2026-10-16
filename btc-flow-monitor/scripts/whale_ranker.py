#!/usr/bin/env python3
"""BTC trader skill screening with strict forward-only fill cursor. PAPER ONLY."""
import datetime as dt, hashlib, json, math, pathlib, re, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]; DATA=ROOT/"data"; API="https://api.hyperliquid.xyz/info"; ADDRESS=re.compile(r"^0x[a-fA-F0-9]{40}$")
MAX_WALLETS=8; MIN_VERIFIED_CLOSES=20; MIN_VERIFIED_DAYS=7; SLIPPAGE_BPS=3.0; MIN_CANDIDATE_CLOSES=20; MIN_CANDIDATE_WIN_RATE=.45; MIN_CANDIDATE_PF=1.05

def query(p):
 r=urllib.request.Request(API,data=json.dumps(p).encode(),headers={"Content-Type":"application/json","User-Agent":"BTC-Flow-Paper-Research/2.1"},method="POST")
 with urllib.request.urlopen(r,timeout=25) as x:return json.load(x)
def key(f):
 # tid/hash are stable exchange identifiers. Include remaining fields only as collision protection.
 raw="|".join(str(f.get(k,"")) for k in ("tid","hash","time","coin","px","sz","side","dir","closedPnl")); return hashlib.sha256(raw.encode()).hexdigest()[:32]
def blank(now):return {"baseline_at":now.isoformat(),"last_observed_at":now.isoformat(),"last_fill_time_ms":0,"seen_at_cursor":[],"new_fills":0,"close_count":0,"win_count":0,"realized_pnl":0.0,"fees":0.0,"notional":0.0,"running_net":0.0,"peak_net":0.0,"max_drawdown":0.0,"close_pnls":[],"initialized":False}
def reset_forward(obs,now,fills):
 # Old schema used a rolling 500-key cache while API can return 2000 fills; old fills re-entered as fresh.
 # Reset contaminated forward counters once, then use monotonic time cursor + IDs at cursor timestamp.
 times=[int(f.get("time",0) or 0) for f in fills]; cursor=max(times,default=0); at={key(f) for f in fills if int(f.get("time",0) or 0)==cursor}
 base=blank(now); base.update({"initialized":True,"last_fill_time_ms":cursor,"seen_at_cursor":sorted(at),"dedup_schema":2,"reset_reason":"ROLLING_KEY_CACHE_CONTAMINATION"}); return base
def update(obs,fills,now):
 if obs.get("dedup_schema")!=2:return reset_forward(obs,now,fills),0
 cursor=int(obs.get("last_fill_time_ms",0)); seen=set(obs.get("seen_at_cursor",[])); ordered=sorted(fills,key=lambda f:(int(f.get("time",0) or 0),key(f))); fresh=[f for f in ordered if int(f.get("time",0) or 0)>cursor or (int(f.get("time",0) or 0)==cursor and key(f) not in seen)]
 for f in fresh:
  pnl=float(f.get("closedPnl") or 0); fee=float(f.get("fee") or 0); px=float(f.get("px") or 0); sz=abs(float(f.get("sz") or 0)); notion=px*sz; close=abs(pnl)>1e-10 or "Close" in str(f.get("dir","")); obs["new_fills"]+=1; obs["fees"]+=fee; obs["notional"]+=notion
  if close:obs["close_count"]+=1; obs["win_count"]+=(pnl>0); obs["realized_pnl"]+=pnl; obs["close_pnls"].append(pnl-fee); obs["close_pnls"]=obs["close_pnls"][-500:]
  d=pnl-fee; obs["running_net"]+=d; obs["peak_net"]=max(obs["peak_net"],obs["running_net"]); obs["max_drawdown"]=max(obs["max_drawdown"],obs["peak_net"]-obs["running_net"])
 if ordered:
  newest=max(int(f.get("time",0) or 0) for f in ordered)
  if newest>cursor:obs["last_fill_time_ms"]=newest; obs["seen_at_cursor"]=sorted({key(f) for f in ordered if int(f.get("time",0) or 0)==newest})
  elif newest==cursor:obs["seen_at_cursor"]=sorted(seen|{key(f) for f in ordered if int(f.get("time",0) or 0)==cursor})
 obs["last_observed_at"]=now.isoformat(); return obs,len(fresh)
def met(v):
 v=[float(x) for x in v]; w=[x for x in v if x>0]; l=[x for x in v if x<0]; gp=sum(w); gl=abs(sum(l)); pf=gp/gl if gl else (99.0 if gp else 0); total=sum(v); conc=max(0,max(v,default=0))/total if total>0 else 1; mean=total/len(v) if v else 0; var=sum((x-mean)**2 for x in v)/len(v) if v else 0; cons=mean/math.sqrt(var) if var>1e-12 else (1 if mean>0 else 0); return pf,conc,cons
def score(a,fills,o,now):
 btc=[x for x in fills if x.get("coin")=="BTC"]; hc=[x for x in btc if abs(float(x.get("closedPnl") or 0))>1e-10 or "Close" in str(x.get("dir",""))]; hv=[float(x.get("closedPnl") or 0)-float(x.get("fee") or 0) for x in hc]; hp=sum(float(x.get("closedPnl") or 0)-float(x.get("fee") or 0) for x in btc); hw=sum(float(x.get("closedPnl") or 0)>0 for x in hc); hpf,hconc,hcons=met(hv); nts=[float(x.get("px") or 0)*abs(float(x.get("sz") or 0)) for x in btc if float(x.get("px") or 0)>0]; ts=[int(x.get("time",0)) for x in btc if int(x.get("time",0))>0]; days=(max(ts)-min(ts))/86400000 if len(ts)>1 else 0; fd=max(0,(now-dt.datetime.fromisoformat(o["baseline_at"].replace("Z","+00:00"))).total_seconds()/86400); c=int(o["close_count"]); w=int(o["win_count"]); fn=o["realized_pnl"]-o["fees"]; sn=fn-o["notional"]*SLIPPAGE_BPS/10000; pf,conc,cons=met(o["close_pnls"]); dd=o["max_drawdown"]; wr=hw/max(1,len(hc)); candidate=len(hc)>=20 and hp>0 and wr>=.45 and hpf>=1.05 and hconc<=.8; verified=fd>=7 and c>=20 and sn>0 and pf>=1.05 and conc<=.65; sample=min(1,c/100); fwr=w/c if c else 0; score=round(100*(.22*fwr+.22*min(1,max(0,(pf-1)/1.5))+.20*(max(0,min(1,sn/(sn+dd+100))) if sn>0 else 0)+.16*max(0,min(1,(cons+.25)/1.25))+.10*max(0,1-min(1,conc))+.10*sample),1) if c else 0
 return {"address":a,"history_sample_fills":len(btc),"history_sample_closes":len(hc),"history_sample_capped":len(fills)>=2000,"history_span_days":round(days,1),"history_sample_net_pnl_usd":round(hp,2),"history_sample_win_rate_pct":round(100*wr,1) if hc else None,"history_profit_factor":round(hpf,2),"history_largest_win_share_pct":round(hconc*100,1),"history_consistency":round(hcons,3),"history_avg_fill_notional_usd":round(sum(nts)/len(nts),2) if nts else 0,"forward_observed_days":round(fd,2),"forward_closes":c,"forward_win_rate_pct":round(100*fwr,1) if c else None,"forward_net_pnl_usd":round(fn,2),"forward_stress_net_pnl_usd":round(sn,2),"forward_profit_factor":round(pf,2),"forward_largest_win_share_pct":round(conc*100,1),"forward_consistency":round(cons,3),"forward_drawdown_usd":round(dd,2),"paper_candidate":candidate,"verified_whale":verified,"eligible_for_paper_observation":verified,"skill_score":score,"dedup_schema":o.get("dedup_schema",2)}
def main():
 DATA.mkdir(parents=True,exist_ok=True); cfg=DATA/"whale-watchlist.json"; aa=json.loads(cfg.read_text()).get("addresses",[]) if cfg.exists() else []; aa=list(dict.fromkeys(str(x).lower() for x in aa));
 if len(aa)>MAX_WALLETS or any(not ADDRESS.fullmatch(x) for x in aa):raise ValueError("invalid watchlist")
 now=dt.datetime.now(dt.timezone.utc); op=DATA/"whale-observations.json"; st=json.loads(op.read_text()) if op.exists() else {"wallets":{}}; st["schema_version"]=3; rr=[]; errors=[]
 for a in aa:
  try:
   fills=query({"type":"userFills","user":a,"aggregateByTime":False}); btc=[x for x in fills if x.get("coin")=="BTC"]; o=st["wallets"].get(a) or blank(now); o,n=update(o,btc,now); st["wallets"][a]=o; rr.append(score(a,fills,o,now))
  except Exception as e:errors.append({"address":a,"error":type(e).__name__})
 st["updated_at"]=now.isoformat(); op.write_text(json.dumps(st,indent=2)+"\n"); rr.sort(key=lambda x:(x["verified_whale"],x["paper_candidate"],x["skill_score"],x["history_sample_net_pnl_usd"]),reverse=True); out={"schema_version":4,"updated_at":now.isoformat(),"paper_only":True,"real_trading_enabled":False,"data_quality":{"dedup_schema":2,"method":"MONOTONIC_FILL_TIME_CURSOR_PLUS_IDS","legacy_forward_counters_reset":True},"candidate_rule":{"min_history_closes":20,"min_history_win_rate_pct":45,"min_profit_factor":1.05,"max_largest_win_share_pct":80},"verification_rule":{"min_forward_days":7,"min_forward_closes":20,"stress_slippage_bps":3,"min_profit_factor":1.05,"max_largest_win_share_pct":65},"ranked_wallets":rr,"errors":errors,"watchlist_count":len(aa),"paper_candidate_count":sum(x["paper_candidate"] for x in rr),"verified_count":sum(x["verified_whale"] for x in rr),"status":"NEEDS_WATCHLIST" if not aa else ("PARTIAL" if errors else "OK")}; (DATA/"whale-ranking.json").write_text(json.dumps(out,indent=2)+"\n"); print("Whale ranking",out["status"],"candidates",out["paper_candidate_count"],"verified",out["verified_count"])
 if errors:raise RuntimeError("wallet API errors")
if __name__=="__main__":main()
