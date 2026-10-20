#!/usr/bin/env python3
"""BTC FLOW adaptive ensemble + independent forward PAPER competition. Never sends orders."""
import json,pathlib,datetime,math
ROOT=pathlib.Path(__file__).resolve().parent;OUT=ROOT/'data/adaptive-meta.json'
ENGINES=('WHALE_COPY','SMART_MONEY','MARKET_STRUCTURE','DERIVATIVES','FIXED_ENSEMBLE','ADAPTIVE_META')
START=1000.;NOTIONAL=500.;FEE=.0005;SLIP=.0003;ENTRY_THRESHOLD=.15

def clamp(x,a,b):return max(a,min(b,x))
def direction(x):return 'LONG' if x>ENTRY_THRESHOLD else 'SHORT' if x<-ENTRY_THRESHOLD else 'WAIT'
def cohort_score(coh,feed):
 wallets=feed.get('wallets',{});vals=[]
 for w in coh.get('wallets',[]):
  s=wallets.get(w.get('address'))
  if s in ('LONG','SHORT'):
   flags=w.get('category_flags',{});q=sum((2 if k in ('WHALE','CONSISTENT','HIGH_PROFIT') else 1) for k,v in flags.items() if v);vals.append((1 if s=='LONG' else -1)*max(1,q))
 return sum(vals)/sum(abs(x) for x in vals) if vals else 0.
def market_structure(hist):
 p=[float(x['price']) for x in hist[-24:] if x.get('price')]
 if len(p)<6:return 0.
 fast=sum(p[-3:])/3;slow=sum(p)/len(p);return clamp((fast/slow-1)*80+(p[-1]/p[0]-1)*20,-1,1)
def derivatives(inp):
 f=float(inp.get('funding_rate') or 0);oi=float(inp.get('oi_change_pct') or 0);liq=float(inp.get('liquidation_bias') or 0)
 return clamp((-f*1000)*.25+clamp(oi/5,-1,1)*.35+clamp(liq,-1,1)*.40,-1,1)
def stats(closed):
 p=[float(x.get('pnl_usd',0)) for x in closed[-100:]]
 if not p:return {'n':0,'expectancy':0.,'pf':None,'win_rate':None,'net':0.}
 w=[x for x in p if x>0];l=[x for x in p if x<0];return {'n':len(p),'expectancy':sum(p)/len(p),'pf':sum(w)/abs(sum(l)) if l else None,'win_rate':100*len(w)/len(p),'net':sum(p)}
def reliability(a):
 s=stats(a.get('closed',[]));n=s['n'];prior=.5
 if not n:return prior
 sample=min(1,n/30);quality=.5+.25*math.tanh(s['expectancy']/5)+.25*math.tanh(((s['pf'] or 1)-1))
 return clamp(prior*(1-sample)+sample*quality,.1,.9)
def account():return {'starting_equity_usd':START,'cash':START,'position':None,'closed':[],'peak':START,'mdd_pct':0.}
def mark(a,price):
 p=a.get('position');u=0.
 if p:u=(price-p['entry_price'])*p['qty']*(1 if p['side']=='LONG' else -1)-price*p['qty']*FEE
 eq=a['cash']+u;a['peak']=max(a.get('peak',START),eq);a['mdd_pct']=max(a.get('mdd_pct',0.),100*(a['peak']-eq)/a['peak'])
 s=stats(a['closed']);a.update({'equity_usd':round(eq,4),'net_pnl_usd':round(eq-START,4),'unrealized_pnl_usd':round(u,4),'closed_count':s['n'],'expectancy_usd':round(s['expectancy'],4),'profit_factor':round(s['pf'],3) if s['pf'] is not None else None,'win_rate_pct':round(s['win_rate'],2) if s['win_rate'] is not None else None,'mdd_pct':round(a['mdd_pct'],3)})
def trade(a,signal,price,now):
 p=a.get('position')
 if p and signal!=p['side']:
  exitp=price*(1-SLIP if p['side']=='LONG' else 1+SLIP);gross=(exitp-p['entry_price'])*p['qty']*(1 if p['side']=='LONG' else -1);fee=exitp*p['qty']*FEE;net=gross-fee-p['entry_fee'];a['cash']+=gross-fee;a['closed'].append({'side':p['side'],'entry_at':p['entry_at'],'exit_at':now,'entry_price':p['entry_price'],'exit_price':exitp,'pnl_usd':round(net,4)});a['closed']=a['closed'][-300:];a['position']=None
  if signal=='WAIT':return
 if not a.get('position') and signal in ('LONG','SHORT'):
  entry=price*(1+SLIP if signal=='LONG' else 1-SLIP);fee=NOTIONAL*FEE
  if a['cash']<=fee:return
  a['cash']-=fee;a['position']={'side':signal,'entry_price':entry,'qty':NOTIONAL/entry,'entry_fee':fee,'entry_at':now}
def advance(state,coh,feed,now,deriv=None):
 if not coh.get('paper_only') or not feed.get('paper_only') or coh.get('real_trading_enabled') or feed.get('real_trading_enabled'):raise ValueError('paper-only flags required')
 price=float(feed.get('btc_mid_usd') or 0)
 if not 1000<price<1000000:raise ValueError('invalid BTC price')
 state.setdefault('history',[]);state.setdefault('accounts',{});state['history'].append({'at':now,'price':price});state['history']=state['history'][-288:]
 smart=cohort_score(coh,feed);structure=market_structure(state['history']);ds=derivatives(deriv or {})
 raw={'WHALE_COPY':smart,'SMART_MONEY':smart,'MARKET_STRUCTURE':structure,'DERIVATIVES':ds};raw['FIXED_ENSEMBLE']=.4*smart+.4*structure+.2*ds
 # weights are based only on completed forward PAPER trades of component engines
 weights={k:reliability(state['accounts'].setdefault(k,account())) for k in ('SMART_MONEY','MARKET_STRUCTURE','DERIVATIVES')};den=sum(weights.values()) or 1;raw['ADAPTIVE_META']=sum(raw[k]*weights[k] for k in weights)/den
 decisions={k:{'score':round(v,4),'signal':direction(v),'confidence':round(abs(v)*100,1)} for k,v in raw.items()}
 for k in ENGINES:
  a=state['accounts'].setdefault(k,account());trade(a,decisions[k]['signal'],price,now);mark(a,price)
 leaderboard=sorted(({'engine':k,'net_pnl_usd':state['accounts'][k]['net_pnl_usd'],'pf':state['accounts'][k]['profit_factor'],'mdd_pct':state['accounts'][k]['mdd_pct'],'trades':state['accounts'][k]['closed_count']} for k in ENGINES),key=lambda x:x['net_pnl_usd'],reverse=True)
 state.update({'schema_version':2,'paper_only':True,'real_trading_enabled':False,'updated_at':now,'btc_mid_usd':price,'engine_weights':weights,'decisions':decisions,'leaderboard':leaderboard,'paper_rules':{'starting_equity_usd':START,'notional_usd':NOTIONAL,'fee_rate':FEE,'slippage_rate':SLIP,'entry_threshold':ENTRY_THRESHOLD},'policy':'Six independent forward PAPER competitors. Adaptive component weights use closed forward trades with 30-trade shrinkage prior. No backfill, no real orders.','control':'WHALE_COPY is the untouched benchmark; ADAPTIVE_META must beat it on forward expectancy/PF/MDD before promotion.'});return state

def main():
 coh=json.loads((ROOT/'trader-discovery/latest.json').read_text());feed=json.loads((ROOT/'trader-discovery/current-positions.json').read_text());state=json.loads(OUT.read_text()) if OUT.exists() else {};now=datetime.datetime.now(datetime.timezone.utc).isoformat();OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(advance(state,coh,feed,now),indent=2)+'\n');print('ADAPTIVE META PAPER COMPETITION PASS')
if __name__=='__main__':main()
