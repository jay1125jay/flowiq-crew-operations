#!/usr/bin/env python3
"""BTC FLOW adaptive ensemble research core. PAPER ONLY; never sends orders."""
import json,pathlib,datetime,math
ROOT=pathlib.Path(__file__).resolve().parent
OUT=ROOT/'data/adaptive-meta.json'
ENGINES=('WHALE_COPY','SMART_MONEY','MARKET_STRUCTURE','DERIVATIVES','FIXED_ENSEMBLE','ADAPTIVE_META')

def clamp(x,a,b):return max(a,min(b,x))
def direction(x):return 'LONG' if x>0.15 else 'SHORT' if x<-0.15 else 'WAIT'
def cohort_score(coh,feed):
 wallets=feed.get('wallets',{});scores=[]
 for w in coh.get('wallets',[]):
  s=wallets.get(w.get('address'))
  if s in ('LONG','SHORT'):
   flags=w.get('category_flags',{});q=sum((2 if k in ('WHALE','CONSISTENT','HIGH_PROFIT') else 1) for k,v in flags.items() if v)
   scores.append((1 if s=='LONG' else -1)*max(1,q))
 return sum(scores)/sum(abs(x) for x in scores) if scores else 0.0
def market_structure(history):
 prices=[float(x['price']) for x in history[-24:] if x.get('price')]
 if len(prices)<6:return 0.0
 fast=sum(prices[-3:])/3;slow=sum(prices)/len(prices);move=(prices[-1]/prices[0]-1)
 return clamp((fast/slow-1)*80+move*20,-1,1)
def derivatives(inp):
 f=float(inp.get('funding_rate') or 0);oi=float(inp.get('oi_change_pct') or 0);liq=float(inp.get('liquidation_bias') or 0)
 return clamp((-f*1000)*.25+clamp(oi/5,-1,1)*.35+clamp(liq,-1,1)*.40,-1,1)
def stats(closed):
 if not closed:return {'n':0,'expectancy':0,'pf':None,'win_rate':None}
 p=[float(x.get('pnl_usd',0)) for x in closed[-50:]];wins=[x for x in p if x>0];loss=[x for x in p if x<0]
 return {'n':len(p),'expectancy':sum(p)/len(p),'pf':sum(wins)/abs(sum(loss)) if loss else None,'win_rate':100*len(wins)/len(p)}
def reliability(account):
 s=stats(account.get('closed',[]));n=s['n'];prior=.5
 if not n:return prior
 exp=math.tanh(s['expectancy']/5);pf=math.tanh(((s['pf'] or 1)-1));sample=min(1,n/30)
 return clamp(prior*(1-sample)+sample*(.5+.25*exp+.25*pf),.1,.9)
def advance(state,coh,feed,now,deriv=None):
 if not coh.get('paper_only') or not feed.get('paper_only') or coh.get('real_trading_enabled') or feed.get('real_trading_enabled'):raise ValueError('paper-only flags required')
 price=float(feed.get('btc_mid_usd') or 0)
 if not 1000<price<1000000:raise ValueError('invalid BTC price')
 state.setdefault('history',[]);state.setdefault('accounts',{})
 state['history'].append({'at':now,'price':price});state['history']=state['history'][-288:]
 smart=cohort_score(coh,feed);structure=market_structure(state['history']);deriv_score=derivatives(deriv or {})
 raw={'WHALE_COPY':smart,'SMART_MONEY':smart,'MARKET_STRUCTURE':structure,'DERIVATIVES':deriv_score}
 fixed=.40*smart+.40*structure+.20*deriv_score;raw['FIXED_ENSEMBLE']=fixed
 weights={k:reliability(state['accounts'].setdefault(k,{'closed':[]})) for k in ('SMART_MONEY','MARKET_STRUCTURE','DERIVATIVES')}
 den=sum(weights.values()) or 1;adaptive=sum(raw[k]*weights[k] for k in weights)/den;raw['ADAPTIVE_META']=adaptive
 decisions={k:{'score':round(v,4),'signal':direction(v),'confidence':round(abs(v)*100,1)} for k,v in raw.items()}
 state.update({'schema_version':1,'paper_only':True,'real_trading_enabled':False,'updated_at':now,'btc_mid_usd':price,'engine_weights':weights,'decisions':decisions,'policy':'Independent research signals. Adaptive weights use only each engine PAPER closed-trade history with a 30-trade shrinkage prior. No real orders.','control':'WHALE_COPY remains the control; ADAPTIVE_META is not promoted without forward evidence.'})
 OUT.parent.mkdir(parents=True,exist_ok=True);return state

def main():
 coh=json.loads((ROOT/'trader-discovery/latest.json').read_text());feed=json.loads((ROOT/'trader-discovery/current-positions.json').read_text());state=json.loads(OUT.read_text()) if OUT.exists() else {};now=datetime.datetime.now(datetime.timezone.utc).isoformat();OUT.write_text(json.dumps(advance(state,coh,feed,now),indent=2)+'\n');print('ADAPTIVE META PAPER PASS')
if __name__=='__main__':main()
