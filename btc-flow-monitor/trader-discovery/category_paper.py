#!/usr/bin/env python3
"""Six independent forward-only simulated BTC ledgers. Never sends orders."""
import json,pathlib,datetime
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'trader-discovery/category-paper.json'
CATS=('WHALE','HIGH_WIN_RATE','HIGH_PROFIT','CONSISTENT','SCALPER','SWING')
def advance(state,coh,feed,now):
 if not coh.get('paper_only') or not feed.get('paper_only'): raise ValueError('paper flag required')
 price=float(feed.get('btc_mid_usd') or 0)
 if not 1000<price<1000000: raise ValueError('invalid BTC price')
 state.setdefault('accounts',{})
 for cat in CATS:
  a=state['accounts'].setdefault(cat,{'cash':1000.0,'positions':{},'baseline':{},'closed':[],'peak':1000.0,'mdd_pct':0.0})
  signals=feed.get('wallets',{})
  eligible={w['address'] for w in coh.get('wallets',[]) if w.get('category_flags',{}).get(cat) and w.get('address') in signals}
  for wallet,p in list(a['positions'].items()):
   if wallet not in eligible or signals.get(wallet)!=p['side']:
    exit_price=price*(0.9997 if p['side']=='LONG' else 1.0003)
    pnl=(exit_price-p['entry'])*p['qty']*(1 if p['side']=='LONG' else -1)-exit_price*p['qty']*0.0005
    a['cash']+=pnl
    a['closed'].append({'wallet':wallet,'pnl_usd':round(pnl-p['fee'],4),'exit_at':now})
    a['closed']=a['closed'][-200:]
    del a['positions'][wallet]
  for wallet in sorted(eligible):
   side=signals[wallet]; previous=a['baseline'].get(wallet); a['baseline'][wallet]=side
   if side not in ('LONG','SHORT') or previous is None or previous==side or wallet in a['positions'] or len(a['positions'])>=3:continue
   entry=price*(1.0003 if side=='LONG' else 0.9997);fee=0.1
   if a['cash']<200:continue
   a['cash']-=fee;a['positions'][wallet]={'side':side,'entry':entry,'qty':200/entry,'fee':fee,'entry_at':now}
  for wallet in list(a['baseline']):
   if wallet not in eligible:del a['baseline'][wallet]
  unreal=sum(((price*(0.9997 if p['side']=='LONG' else 1.0003)-p['entry'])*p['qty']*(1 if p['side']=='LONG' else -1)-price*p['qty']*0.0005) for p in a['positions'].values())
  equity=a['cash']+unreal;a['peak']=max(a['peak'],equity);a['mdd_pct']=max(a['mdd_pct'],100*(a['peak']-equity)/a['peak'])
  wins=sum(t['pnl_usd']>0 for t in a['closed'])
  a.update({'equity_usd':round(equity,4),'net_pnl_usd':round(equity-1000,4),'mdd_pct':round(a['mdd_pct'],3),'closed_count':len(a['closed']),'win_rate_pct':round(wins/len(a['closed'])*100,2) if a['closed'] else None,'open_count':len(a['positions']),'eligible_observed':len(eligible)})
 state.update({'paper_only':True,'real_trading_enabled':False,'updated_at':now,'limitation':'Only previously observed wallet directions are used; no historical backfill or exchange orders; estimated fees/slippage, funding excluded.'})
 return state
def main():
 state=json.loads(OUT.read_text()) if OUT.exists() else {}
 coh=json.loads((ROOT/'trader-discovery/latest.json').read_text())
 feed=json.loads((ROOT/'data/whale-paper-state.json').read_text())
 now=datetime.datetime.now(datetime.timezone.utc).isoformat()
 OUT.write_text(json.dumps(advance(state,coh,feed,now),indent=2)+'\n')
 print('CATEGORY PAPER PASS')
if __name__=='__main__':main()
