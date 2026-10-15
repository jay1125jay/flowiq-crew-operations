#!/usr/bin/env python3
"""Candidate whale position PAPER follower. Never places orders.
Independent 1x..10x PAPER futures accounts with account-level risk limits.
"""
import datetime as dt
import json
import pathlib
import urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1];DATA=ROOT/"data";STATE=DATA/"whale-paper-state.json";RANK=DATA/"whale-ranking.json"
API="https://api.hyperliquid.xyz/info";START_EQUITY=1000.0;BASE_MARGIN_USD=200.0;MAX_MARGIN_USAGE=0.60
FEE_BPS=5.0;SLIP_BPS=3.0;MAX_RANK_AGE_HOURS=3;MAX_POSITIONS=3;LEVERAGE_TESTS=tuple(range(1,11));FUNDING_RATE_8H=0.0001;MAINT_MARGIN_RATE=0.005

def api(payload):
 req=urllib.request.Request(API,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","User-Agent":"BTC-Flow-Paper-Research/1.4"},method="POST")
 with urllib.request.urlopen(req,timeout=25) as res:return json.load(res)
def direction(state):
 for item in state.get("assetPositions",[]):
  p=item.get("position",{})
  if p.get("coin")=="BTC":
   z=float(p.get("szi") or 0);return "LONG" if z>0 else "SHORT" if z<0 else "FLAT"
 return "FLAT"
def execution(price,side,opening):
 buy=(side=="LONG")==opening;return price*(1+(SLIP_BPS/10000)*(1 if buy else -1))
def liquid_price(entry,side,lev):
 move=max(0.0,1.0/lev-MAINT_MARGIN_RATE);return entry*(1-move) if side=="LONG" else entry*(1+move)
def funding_cost(p,now):
 opened=dt.datetime.fromisoformat(p["entry_at"].replace("Z","+00:00"));hours=max(0.0,(now-opened).total_seconds()/3600);return p["notional_usd"]*FUNDING_RATE_8H*(hours/8)
def init_accounts(state):
 a=state.get("leverage_accounts")
 if a:return a
 a={str(l):{"leverage":l,"starting_equity_usd":START_EQUITY,"cash_usd":START_EQUITY,"realized_net_pnl_usd":0.0,"funding_paid_usd":0.0,"positions":{},"closed_trades":[],"liquidations":0,"risk_blocks":0} for l in LEVERAGE_TESTS};state["leverage_accounts"]=a;return a
def used_margin(acct):return sum(float(p.get("margin_usd",0)) for p in acct["positions"].values())
def close_position(acct,addr,price,now,reason):
 p=acct["positions"].pop(addr,None)
 if not p:return
 exit_px=execution(price,p["side"],False);gross=(exit_px-p["entry_price"])*p["quantity_btc"]*(1 if p["side"]=="LONG" else -1);exit_fee=abs(exit_px*p["quantity_btc"])*FEE_BPS/10000;fund=funding_cost(p,now);net=gross-p["entry_fee_usd"]-exit_fee-fund
 acct["cash_usd"]+=gross-exit_fee-fund;acct["realized_net_pnl_usd"]+=net;acct["funding_paid_usd"]+=fund
 if reason=="LIQUIDATED":acct["liquidations"]+=1
 acct["closed_trades"].append({"wallet":addr,"side":p["side"],"leverage":acct["leverage"],"entry_at":p["entry_at"],"exit_at":now.isoformat(),"entry_price":p["entry_price"],"exit_price":exit_px,"notional_usd":p["notional_usd"],"margin_usd":p["margin_usd"],"entry_fee_usd":round(p["entry_fee_usd"],6),"exit_fee_usd":round(exit_fee,6),"funding_usd":round(fund,6),"gross_pnl_usd":round(gross,6),"net_pnl_usd":round(net,4),"reason":reason})
def open_position(acct,addr,side,price,now,verified):
 lev=acct["leverage"];used=used_margin(acct);equity=max(0.0,float(acct.get("estimated_equity_usd",acct["cash_usd"])));limit=min(START_EQUITY*MAX_MARGIN_USAGE,equity*MAX_MARGIN_USAGE);available=max(0.0,limit-used);margin=min(BASE_MARGIN_USD,available)
 if margin<BASE_MARGIN_USD-1e-9:acct["risk_blocks"]=acct.get("risk_blocks",0)+1;return False
 notional=margin*lev;entry=execution(price,side,True);qty=notional/entry;fee=notional*FEE_BPS/10000;acct["cash_usd"]-=fee;acct["positions"][addr]={"side":side,"entry_price":entry,"quantity_btc":qty,"notional_usd":notional,"margin_usd":margin,"entry_fee_usd":fee,"entry_at":now.isoformat(),"liquidation_price":liquid_price(entry,side,lev),"verified_at_entry":verified};return True
def mark_accounts(accounts,price,now):
 for acct in accounts.values():
  for addr,p in list(acct["positions"].items()):
   hit=(p["side"]=="LONG" and price<=p["liquidation_price"]) or (p["side"]=="SHORT" and price>=p["liquidation_price"])
   if hit:close_position(acct,addr,p["liquidation_price"],now,"LIQUIDATED")
  unreal=0.0;accrued=0.0
  for p in acct["positions"].values():
   exit_px=execution(price,p["side"],False);gross=(exit_px-p["entry_price"])*p["quantity_btc"]*(1 if p["side"]=="LONG" else -1);exit_fee=abs(exit_px*p["quantity_btc"])*FEE_BPS/10000;fund=funding_cost(p,now);unreal+=gross-exit_fee-fund;accrued+=fund
  acct["unrealized_pnl_usd"]=round(unreal,4);acct["accrued_funding_usd"]=round(accrued,4);acct["estimated_equity_usd"]=round(acct["cash_usd"]+unreal,4);acct["open_positions"]=len(acct["positions"]);acct["closed_trade_count"]=len(acct["closed_trades"]);acct["margin_used_usd"]=round(used_margin(acct),4);acct["margin_limit_usd"]=round(min(START_EQUITY*MAX_MARGIN_USAGE,max(0,acct["estimated_equity_usd"])*MAX_MARGIN_USAGE),4);acct["margin_usage_pct"]=round(100*acct["margin_used_usd"]/START_EQUITY,2);acct["free_equity_usd"]=round(max(0,acct["estimated_equity_usd"]-acct["margin_used_usd"]),4);acct["paper_only"]=True
def main():
 now=dt.datetime.now(dt.timezone.utc);DATA.mkdir(parents=True,exist_ok=True);state=json.loads(STATE.read_text()) if STATE.exists() else {"paper_only":True,"wallets":{}};state["schema_version"]=5;state["paper_only"]=True;accounts=init_accounts(state);rank=json.loads(RANK.read_text()) if RANK.exists() else None;reason="RANKING_MISSING";selected=[];verified=set()
 if rank and rank.get("status")=="OK" and not rank.get("errors"):
  try:
   age=(now-dt.datetime.fromisoformat(rank["updated_at"].replace("Z","+00:00"))).total_seconds()/3600
   if 0<=age<=MAX_RANK_AGE_HOURS:
    rows=rank.get("ranked_wallets",[]);selected=[w["address"] for w in rows if w.get("paper_candidate") or w.get("verified_whale")][:MAX_POSITIONS];verified={w["address"] for w in rows if w.get("verified_whale")};reason="PAPER_VALIDATING" if selected else "NO_PAPER_CANDIDATES"
   else:reason="RANKING_STALE"
  except (ValueError,KeyError,TypeError):reason="RANKING_INVALID"
 price=float(api({"type":"allMids"})["BTC"])
 if not 1000<price<1000000:raise ValueError("invalid BTC mid")
 mark_accounts(accounts,price,now);events=[]
 for addr in selected:
  observed=direction(api({"type":"clearinghouseState","user":addr}));previous=state.setdefault("wallets",{}).get(addr);state["wallets"][addr]=observed
  if previous is None:events.append({"wallet":addr,"action":"BASELINE_ONLY","direction":observed});continue
  if observed==previous:continue
  opened=0;blocked=0
  for acct in accounts.values():
   close_position(acct,addr,price,now,"WHALE_DIRECTION_CHANGED")
   if observed!="FLAT" and len(acct["positions"])<MAX_POSITIONS:
    if open_position(acct,addr,observed,price,now,addr in verified):opened+=1
    else:blocked+=1
  events.append({"wallet":addr,"action":"DIRECTION_CHANGE","from":previous,"to":observed,"accounts_opened":opened,"risk_blocked":blocked})
 mark_accounts(accounts,price,now);base=accounts["1"]
 state.update({"updated_at":now.isoformat(),"btc_mid_usd":price,"status":reason,"selected_candidate_wallets":len(selected),"verified_wallets":len(verified),"events_latest":events,"leverage_test_mode":"INDEPENDENT_1X_TO_10X_FUTURES_PAPER","risk_policy":{"base_margin_per_position_usd":BASE_MARGIN_USD,"max_margin_usage_pct":MAX_MARGIN_USAGE*100,"max_positions":MAX_POSITIONS},"funding_model":{"rate_per_8h":FUNDING_RATE_8H,"type":"ESTIMATED_CONSTANT"},"maintenance_margin_rate":MAINT_MARGIN_RATE,"starting_equity_usd":START_EQUITY,"cash_usd":base["cash_usd"],"realized_net_pnl_usd":base["realized_net_pnl_usd"],"unrealized_pnl_usd":base["unrealized_pnl_usd"],"estimated_equity_usd":base["estimated_equity_usd"],"open_positions":base["open_positions"],"closed_trade_count":base["closed_trade_count"],"positions":base["positions"],"closed_trades":base["closed_trades"]});STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print("PAPER",reason,"1x-10x","risk cap",MAX_MARGIN_USAGE,"events",len(events))
if __name__=="__main__":main()
