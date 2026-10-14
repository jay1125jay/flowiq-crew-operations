#!/usr/bin/env python3
"""Public BTC whale skill screening. PAPER ONLY. No private credentials or orders."""
import datetime as dt
import json
import math
import os
import pathlib
import re
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = "https://api.hyperliquid.xyz/info"
ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")
MAX_WALLETS = 8
MIN_CLOSES = 20
MIN_DAYS = 7
FEE_BPS = 5  # conservative illustrative per-side taker fee; not a quote
SLIPPAGE_BPS = 3  # per-side stress assumption

def query(payload):
    req = urllib.request.Request(API, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json","User-Agent":"BTC-Flow-Paper-Research/1.0"},method="POST")
    with urllib.request.urlopen(req,timeout=25) as r:
        return json.load(r)

def score_wallet(address, now_ms):
    fills = query({"type":"userFills","user":address,"aggregateByTime":False})
    btc = sorted((x for x in fills if x.get("coin") == "BTC"),key=lambda x:int(x.get("time",0)))
    recent = [x for x in btc if int(x.get("time",0)) >= now_ms - 90*86400000]
    closes = [x for x in recent if abs(float(x.get("closedPnl") or 0)) > 1e-10 or "Close" in x.get("dir","")]
    pnl = sum(float(x.get("closedPnl") or 0) - float(x.get("fee") or 0) for x in recent)
    winners = sum(1 for x in closes if float(x.get("closedPnl") or 0) > 0)
    first = int(recent[0]["time"]) if recent else 0
    days = (now_ms-first)/86400000 if first else 0
    eligible = len(closes)>=MIN_CLOSES and days>=MIN_DAYS and pnl>0
    # Observed closed-PnL only; not a full equity drawdown or full historical performance.
    running = peak = max_dd = 0.0
    for f in recent:
        running += float(f.get("closedPnl") or 0)-float(f.get("fee") or 0)
        peak=max(peak,running)
        max_dd=max(max_dd,peak-running)
    notional = sum(abs(float(x.get("px") or 0)*float(x.get("sz") or 0)) for x in recent)
    cost_stress = notional * (FEE_BPS+SLIPPAGE_BPS)/10000
    stress_pnl = sum(float(x.get("closedPnl") or 0) for x in recent)-cost_stress
    # No trading recommendation from sparse samples.
    score = round(100*(0.45*min(1,max(0,stress_pnl)/max(1,max_dd+100))+
                       0.35*(winners/max(1,len(closes)))+
                       0.20*min(1,len(closes)/100)),1) if eligible and stress_pnl>0 else 0
    return {"address":address,"btc_fills_90d":len(recent),"btc_closes_90d":len(closes),
            "observed_days":round(days,1),"observed_net_pnl_usd":round(pnl,2),
            "stress_net_pnl_usd":round(stress_pnl,2),
            "observed_closed_pnl_drawdown_usd":round(max_dd,2),
            "win_rate_observed_pct":round(100*winners/len(closes),1) if closes else None,
            "eligible_for_paper_observation":bool(eligible and stress_pnl>0),
            "skill_score":score,
            "caveat":"Recent fills limited by API; drawdown is NOT account equity MDD; execution lag not modeled."}

def main():
    cfg=ROOT/"data"/"whale-watchlist.json"
    addresses=json.loads(cfg.read_text(encoding="utf-8")).get("addresses",[]) if cfg.exists() else []
    if not isinstance(addresses,list): raise ValueError("addresses must be a list")
    addresses=list(dict.fromkeys(str(x).lower() for x in addresses))
    if len(addresses)>MAX_WALLETS or any(not ADDRESS.fullmatch(x) for x in addresses):
        raise ValueError("invalid watchlist: max 8 valid addresses")
    now=dt.datetime.now(dt.timezone.utc)
    results=[]; errors=[]
    for a in addresses:
        try: results.append(score_wallet(a,int(now.timestamp()*1000)))
        except Exception as e: errors.append({"address":a,"error":type(e).__name__})
    results.sort(key=lambda x:(x["eligible_for_paper_observation"],x["skill_score"]),reverse=True)
    out={"schema_version":1,"updated_at":now.isoformat(),"paper_only":True,"real_trading_enabled":False,
         "selection_is_not_proof_of_profitability":True,"min_closes":MIN_CLOSES,"min_observed_days":MIN_DAYS,
         "ranked_wallets":results,"errors":errors,"watchlist_count":len(addresses),
         "status":"NEEDS_WATCHLIST" if not addresses else ("PARTIAL" if errors else "OK")}
    target=ROOT/"data"/"whale-ranking.json"
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Whale ranking",out["status"],len(results),"wallets")
    if errors: raise RuntimeError("Some wallet API requests failed; stale rankings must not be treated as fresh")

if __name__=="__main__":main()
