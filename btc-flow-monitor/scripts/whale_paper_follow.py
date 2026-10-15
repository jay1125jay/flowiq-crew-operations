#!/usr/bin/env python3
"""Candidate whale position PAPER follower. Never places orders.
Historical samples only nominate candidates. First observation is baseline-only.
Forward PAPER results are the source of truth for copyability.
"""
import datetime as dt
import json
import pathlib
import urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
STATE=DATA/"whale-paper-state.json"
RANK=DATA/"whale-ranking.json"
API="https://api.hyperliquid.xyz/info"
START_EQUITY=1000.0
MAX_NOTIONAL=200.0
FEE_BPS=5.0
SLIP_BPS=3.0
MAX_RANK_AGE_HOURS=3
MAX_POSITIONS=3

def api(payload):
    req=urllib.request.Request(API,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","User-Agent":"BTC-Flow-Paper-Research/1.1"},method="POST")
    with urllib.request.urlopen(req,timeout=25) as res:return json.load(res)

def direction(state):
    for item in state.get("assetPositions",[]):
        p=item.get("position",{})
        if p.get("coin")=="BTC":
            size=float(p.get("szi") or 0)
            return "LONG" if size>0 else "SHORT" if size<0 else "FLAT"
    return "FLAT"

def execution(price,side,opening):
    buy=(side=="LONG")==opening
    return price*(1+(SLIP_BPS/10000)*(1 if buy else -1))

def main():
    now=dt.datetime.now(dt.timezone.utc)
    DATA.mkdir(parents=True,exist_ok=True)
    state=json.loads(STATE.read_text()) if STATE.exists() else {"schema_version":2,"paper_only":True,"starting_equity_usd":START_EQUITY,"cash_usd":START_EQUITY,"realized_net_pnl_usd":0.0,"wallets":{},"positions":{},"closed_trades":[]}
    state["schema_version"]=2
    rank=json.loads(RANK.read_text()) if RANK.exists() else None
    reason="RANKING_MISSING"; selected=[]; verified=set()
    if rank and rank.get("status")=="OK" and not rank.get("errors"):
        try:
            age=(now-dt.datetime.fromisoformat(rank["updated_at"].replace("Z","+00:00"))).total_seconds()/3600
            if 0<=age<=MAX_RANK_AGE_HOURS:
                rows=rank.get("ranked_wallets",[])
                selected=[w["address"] for w in rows if w.get("paper_candidate") or w.get("verified_whale")][:MAX_POSITIONS]
                verified={w["address"] for w in rows if w.get("verified_whale")}
                reason="PAPER_VALIDATING" if selected else "NO_PAPER_CANDIDATES"
            else:reason="RANKING_STALE"
        except (ValueError,KeyError,TypeError):reason="RANKING_INVALID"
    price=float(api({"type":"allMids"})["BTC"])
    if not 1000<price<1000000:raise ValueError("invalid BTC mid")
    events=[]
    for addr in selected:
        observed=direction(api({"type":"clearinghouseState","user":addr}))
        previous=state["wallets"].get(addr)
        state["wallets"][addr]=observed
        if previous is None:
            events.append({"wallet":addr,"action":"BASELINE_ONLY","direction":observed,"verified":addr in verified})
            continue
        if observed==previous:continue
        old=state["positions"].pop(addr,None)
        if old:
            exit_px=execution(price,old["side"],False)
            gross=(exit_px-old["entry_price"])*old["quantity"]*(1 if old["side"]=="LONG" else -1)
            exit_fee=abs(exit_px*old["quantity"])*FEE_BPS/10000
            net=gross-exit_fee-old["entry_fee"]
            state["cash_usd"]+=gross-exit_fee
            state["realized_net_pnl_usd"]+=net
            state["closed_trades"].append({"wallet":addr,"side":old["side"],"entry_at":old["entry_at"],"exit_at":now.isoformat(),"entry_price":old["entry_price"],"exit_price":exit_px,"quantity_btc":old["quantity"],"entry_fee_usd":round(old["entry_fee"],6),"exit_fee_usd":round(exit_fee,6),"total_fee_usd":round(old["entry_fee"]+exit_fee,6),"gross_pnl_usd":round(gross,6),"net_pnl_usd":round(net,4),"verified_at_exit":addr in verified,"reason":"WHALE_DIRECTION_CHANGED"})
            events.append({"wallet":addr,"action":"CLOSE","net_pnl_usd":round(net,4)})
        if observed!="FLAT" and len(state["positions"])<MAX_POSITIONS:
            entry=execution(price,observed,True);qty=MAX_NOTIONAL/entry;fee=MAX_NOTIONAL*FEE_BPS/10000
            state["cash_usd"]-=fee
            state["positions"][addr]={"side":observed,"entry_price":entry,"quantity":qty,"entry_fee":fee,"entry_at":now.isoformat(),"verified_at_entry":addr in verified}
            events.append({"wallet":addr,"action":"OPEN","direction":observed,"verified":addr in verified})
    state["updated_at"]=now.isoformat();state["btc_mid_usd"]=price;state["status"]=reason
    state["selected_candidate_wallets"]=len(selected);state["verified_wallets"]=len(verified)
    state["open_positions"]=len(state["positions"]);state["closed_trade_count"]=len(state["closed_trades"]);state["events_latest"]=events
    state["unrealized_pnl_usd"]=round(sum((execution(price,p["side"],False)-p["entry_price"])*p["quantity"]*(1 if p["side"]=="LONG" else -1)-abs(execution(price,p["side"],False)*p["quantity"])*FEE_BPS/10000 for p in state["positions"].values()),4)
    state["estimated_equity_usd"]=round(state["cash_usd"]+state["unrealized_pnl_usd"],4)
    STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("PAPER",reason,"candidates",len(selected),"verified",len(verified),"events",len(events))

if __name__=="__main__":main()
