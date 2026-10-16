#!/usr/bin/env python3
"""BTC trader skill screening with forward-only observations. PAPER ONLY; never places orders."""
import datetime as dt, hashlib, json, math, pathlib, re, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]; DATA=ROOT/"data"; API="https://api.hyperliquid.xyz/info"; ADDRESS=re.compile(r"^0x[a-fA-F0-9]{40}$")
MAX_WALLETS=8; MIN_VERIFIED_CLOSES=20; MIN_VERIFIED_DAYS=7; SLIPPAGE_BPS=3.0; RECENT_KEYS_MAX=500; MIN_CANDIDATE_CLOSES=20; MIN_CANDIDATE_WIN_RATE=0.45; MIN_CANDIDATE_PF=1.05

def query(payload):
 req=urllib.request.Request(API,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","User-Agent":"BTC-Flow-Paper-Research/2.0"},method="POST")
 with urllib.request.urlopen(req,timeout=25) as r:return json.load(r)
def fill_key(f):
 raw="|".join(str(f.get(k,"")) for k in ("time","hash","tid","px","sz","side","dir","closedPnl")); return hashlib.sha256(raw.encode()).hexdigest()[:24]
def blank_obs(now):
 return {"baseline_at":now.isoformat(),"last_observed_at":now.isoformat(),"recent_keys":[],"new_fills":0,"close_count":0,"win_count":0,"realized_pnl":0.0,"fees":0.0,"notional":0.0,"running_net":0.0,"peak_net":0.0,"max_drawdown":0.0,"close_pnls":[]}
def update_forward(obs,fills,now):
 seen=set(obs.get("recent_keys",[])); fresh=[f for f in sorted(fills,key=lambda x:int(x.get("time",0))) if fill_key(f) not in seen]
 if not obs.get("initialized"):
  obs["recent_keys"]=[fill_key(f) for f in fills[-RECENT_KEYS_MAX:]]; obs["initialized"]=True; obs["last_observed_at"]=now.isoformat(); return obs,0
 for f in fresh:
  pnl=float(f.get("closedPnl") or 0); fee=float(f.get("fee") or 0); px=float(f.get("px") or 0); sz=abs(float(f.get("sz") or 0)); notional=px*sz; is_close=abs(pnl)>1e-10 or "Close" in str(f.get("dir",""))
  obs["new_fills"]=int(obs.get("new_fills",0))+1; obs["fees"]=float(obs.get("fees",0))+fee; obs["notional"]=float(obs.get("notional",0))+notional
  if is_close:
   obs["close_count"]=int(obs.get("close_count",0))+1; obs["win_count"]=int(obs.get("win_count",0))+(1 if pnl>0 else 0); obs["realized_pnl"]=float(obs.get("realized_pnl",0))+pnl; obs.setdefault("close_pnls",[]).append(pnl-fee); obs["close_pnls"]=obs["close_pnls"][-500:]
  net_delta=pnl-fee; obs["running_net"]=float(obs.get("running_net",0))+net_delta; obs["peak_net"]=max(float(obs.get("peak_net",0)),obs["running_net"]); obs["max_drawdown"]=max(float(obs.get("max_drawdown",0)),obs["peak_net"]-obs["running_net"])
 obs["recent_keys"]=list(dict.fromkeys([fill_key(f) for f in fills[-RECENT_KEYS_MAX:]]+obs.get("recent_keys",[])))[:RECENT_KEYS_MAX]; obs["last_observed_at"]=now.isoformat(); return obs,len(fresh)
def metrics(values):
 vals=[float(x) for x in values]; wins=[x for x in vals if x>0]; losses=[x for x in vals if x<0]; gp=sum(wins); gl=abs(sum(losses)); pf=(gp/gl) if gl>0 else (99.0 if gp>0 else 0.0); total=sum(vals); largest=max(vals) if vals else 0.0; concentration=(max(0.0,largest)/total) if total>0 else 1.0
 mean=total/len(vals) if vals else 0.0; variance=sum((x-mean)**2 for x in vals)/len(vals) if vals else 0.0; consistency=(mean/math.sqrt(variance)) if variance>1e-12 else (1.0 if mean>0 else 0.0)
 return pf,concentration,consistency
def score_wallet(address,fills,obs,now):
 btc=[x for x in fills if x.get("coin")=="BTC"]; hist_closes=[x for x in btc if abs(float(x.get("closedPnl") or 0))>1e-10 or "Close" in str(x.get("dir",""))]; hist_vals=[float(x.get("closedPnl") or 0)-float(x.get("fee") or 0) for x in hist_closes]; hist_pnl=sum(float(x.get("closedPnl") or 0)-float(x.get("fee") or 0) for x in btc); hist_wins=sum(1 for x in hist_closes if float(x.get("closedPnl") or 0)>0); hist_pf,hist_conc,hist_cons=metrics(hist_vals); notionals=[float(x.get("px") or 0)*abs(float(x.get("sz") or 0)) for x in btc if float(x.get("px") or 0)>0]; avg_notional=sum(notionals)/len(notionals) if notionals else 0.0
 times=[int(x.get("time",0)) for x in btc if int(x.get("time",0))>0]; history_days=((max(times)-min(times))/86400000) if len(times)>=2 else 0.0; capped=len(fills)>=2000; baseline=dt.datetime.fromisoformat(obs["baseline_at"].replace("Z","+00:00")); forward_days=max(0.0,(now-baseline).total_seconds()/86400); closes=int(obs.get("close_count",0)); wins=int(obs.get("win_count",0)); forward_net=float(obs.get("realized_pnl",0))-float(obs.get("fees",0)); stress_net=forward_net-float(obs.get("notional",0))*SLIPPAGE_BPS/10000; fpf,fconc,fcons=metrics(obs.get("close_pnls",[])); dd=float(obs.get("max_drawdown",0)); winrate=hist_wins/max(1,len(hist_closes)); candidate=len(hist_closes)>=MIN_CANDIDATE_CLOSES and hist_pnl>0 and winrate>=MIN_CANDIDATE_WIN_RATE and hist_pf>=MIN_CANDIDATE_PF and hist_conc<=0.80
 verified=forward_days>=MIN_VERIFIED_DAYS and closes>=MIN_VERIFIED_CLOSES and stress_net>0 and fpf>=1.05 and fconc<=0.65
 sample=min(1.0,closes/100); wr=(wins/closes) if closes else 0.0; pfscore=min(1.0,max(0.0,(fpf-1)/1.5)) if closes else 0.0; ddscore=max(0.0,min(1.0,stress_net/(stress_net+dd+100))) if stress_net>0 else 0.0; consscore=max(0.0,min(1.0,(fcons+0.25)/1.25)) if closes else 0.0; concentration_score=max(0.0,1-min(1.0,fconc)) if closes else 0.0; score=round(100*(.22*wr+.22*pfscore+.20*ddscore+.16*consscore+.10*concentration_score+.10*sample),1) if closes else 0.0
 return {"address":address,"history_sample_fills":len(btc),"history_sample_closes":len(hist_closes),"history_sample_capped":capped,"history_span_days":round(history_days,1),"history_sample_net_pnl_usd":round(hist_pnl,2),"history_sample_win_rate_pct":round(100*winrate,1) if hist_closes else None,"history_profit_factor":round(hist_pf,2),"history_largest_win_share_pct":round(hist_conc*100,1),"history_consistency":round(hist_cons,3),"history_avg_fill_notional_usd":round(avg_notional,2),"forward_observed_days":round(forward_days,2),"forward_closes":closes,"forward_win_rate_pct":round(100*wins/closes,1) if closes else None,"forward_net_pnl_usd":round(forward_net,2),"forward_stress_net_pnl_usd":round(stress_net,2),"forward_profit_factor":round(fpf,2),"forward_largest_win_share_pct":round(fconc*100,1),"forward_consistency":round(fcons,3),"forward_drawdown_usd":round(dd,2),"paper_candidate":candidate,"verified_whale":verified,"eligible_for_paper_observation":verified,"skill_score":score,"caveat":"History only seeds candidates. Verification requires forward profitability, PF, diversification and drawdown-aware evidence."}
def main():
 DATA.mkdir(parents=True,exist_ok=True); cfg=DATA/"whale-watchlist.json"; addresses=json.loads(cfg.read_text(encoding="utf-8")).get("addresses",[]) if cfg.exists() else []; addresses=list(dict.fromkeys(str(x).lower() for x in addresses));
 if len(addresses)>MAX_WALLETS or any(not ADDRESS.fullmatch(x) for x in addresses):raise ValueError("invalid watchlist")
 now=dt.datetime.now(dt.timezone.utc); obs_path=DATA/"whale-observations.json"; store=json.loads(obs_path.read_text(encoding="utf-8")) if obs_path.exists() else {"schema_version":2,"wallets":{}}; store["schema_version"]=2; results=[]; errors=[]
 for a in addresses:
  try:
   fills=query({"type":"userFills","user":a,"aggregateByTime":False}); btc=[x for x in fills if x.get("coin")=="BTC"]; obs=store["wallets"].get(a) or blank_obs(now); obs.setdefault("close_pnls",[]); obs,_=update_forward(obs,btc,now); store["wallets"][a]=obs; results.append(score_wallet(a,fills,obs,now))
  except Exception as e:errors.append({"address":a,"error":type(e).__name__})
 store["updated_at"]=now.isoformat(); obs_path.write_text(json.dumps(store,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); results.sort(key=lambda x:(x["verified_whale"],x["paper_candidate"],x["skill_score"],x["history_sample_net_pnl_usd"]),reverse=True)
 out={"schema_version":3,"updated_at":now.isoformat(),"paper_only":True,"real_trading_enabled":False,"candidate_rule":{"min_history_closes":MIN_CANDIDATE_CLOSES,"min_history_win_rate_pct":MIN_CANDIDATE_WIN_RATE*100,"min_profit_factor":MIN_CANDIDATE_PF,"max_largest_win_share_pct":80},"verification_rule":{"min_forward_days":MIN_VERIFIED_DAYS,"min_forward_closes":MIN_VERIFIED_CLOSES,"stress_slippage_bps":SLIPPAGE_BPS,"min_profit_factor":1.05,"max_largest_win_share_pct":65},"ranked_wallets":results,"errors":errors,"watchlist_count":len(addresses),"paper_candidate_count":sum(1 for x in results if x["paper_candidate"]),"verified_count":sum(1 for x in results if x["verified_whale"]),"status":"NEEDS_WATCHLIST" if not addresses else ("PARTIAL" if errors else "OK")}; (DATA/"whale-ranking.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print("Whale ranking",out["status"],"candidates",out["paper_candidate_count"],"verified",out["verified_count"])
 if errors:raise RuntimeError("wallet API errors")
if __name__=="__main__":main()
