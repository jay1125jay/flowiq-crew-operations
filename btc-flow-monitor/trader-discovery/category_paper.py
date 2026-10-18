#!/usr/bin/env python3
"""Six independent forward-only simulated BTC follower ledgers. Never sends orders."""
import json,pathlib,datetime
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'trader-discovery/category-paper.json'
CATS=('WHALE','HIGH_WIN_RATE','HIGH_PROFIT','CONSISTENT','SCALPER','SWING')
MAX_POSITIONS=6
NOTIONAL_USD=150.0
SLIPPAGE=0.0003
FEE_RATE=0.0005

def _close(a,wallet,p,price,now,reason):
 exit_price=price*(1-SLIPPAGE if p['side']=='LONG' else 1+SLIPPAGE)
 gross=(exit_price-p['entry'])*p['qty']*(1 if p['side']=='LONG' else -1)
 exit_fee=exit_price*p['qty']*FEE_RATE
 net=gross-exit_fee-p['fee']
 a['cash']+=gross-exit_fee
 a['closed'].append({'wallet':wallet,'side':p['side'],'pnl_usd':round(net,4),'exit_at':now,'reason':reason})
 a['closed']=a['closed'][-300:]
 del a['positions'][wallet]

def advance(state,coh,feed,now):
 if not coh.get('paper_only') or not feed.get('paper_only'): raise ValueError('paper flag required')
 price=float(feed.get('btc_mid_usd') or 0)
 if not 1000<price<1000000: raise ValueError('invalid BTC price')
 signals=feed.get('wallets',{})
 state.setdefault('accounts',{})
 for cat in CATS:
  a=state['accounts'].setdefault(cat,{'cash':1000.0,'positions':{},'closed':[],'peak':1000.0,'mdd_pct':0.0})
  # Backward-compatible cleanup: the old engine used baseline gating. It is no longer needed.
  a.pop('baseline',None)
  eligible={w['address'] for w in coh.get('wallets',[]) if w.get('category_flags',{}).get(cat) and w.get('address') in signals}
  # Follow exits and flips first. A flip closes the old side, then may reopen below at the newly observed side.
  for wallet,p in list(a['positions'].items()):
   new_side=signals.get(wallet)
   if wallet not in eligible:
    _close(a,wallet,p,price,now,'NO_LONGER_ELIGIBLE')
   elif new_side not in ('LONG','SHORT'):
    _close(a,wallet,p,price,now,'SOURCE_FLAT')
   elif new_side!=p['side']:
    _close(a,wallet,p,price,now,'SOURCE_FLIP')
  # Immediate forward-only entry: if an eligible wallet is already LONG/SHORT when first observed,
  # enter PAPER now at the current BTC price plus estimated slippage. No historical PnL is imported.
  for wallet in sorted(eligible):
   side=signals.get(wallet)
   if side not in ('LONG','SHORT') or wallet in a['positions'] or len(a['positions'])>=MAX_POSITIONS: continue
   entry=price*(1+SLIPPAGE if side=='LONG' else 1-SLIPPAGE)
   notional=NOTIONAL_USD
   entry_fee=notional*FEE_RATE
   if a['cash']<entry_fee: continue
   a['cash']-=entry_fee
   a['positions'][wallet]={'side':side,'entry':entry,'qty':notional/entry,'notional_usd':notional,'fee':entry_fee,'entry_at':now,'entry_reason':'FOLLOW_CURRENT_OBSERVED_POSITION'}
  unreal=sum(((price*(1-SLIPPAGE if p['side']=='LONG' else 1+SLIPPAGE)-p['entry'])*p['qty']*(1 if p['side']=='LONG' else -1)-price*p['qty']*FEE_RATE) for p in a['positions'].values())
  equity=a['cash']+unreal;a['peak']=max(a['peak'],equity);a['mdd_pct']=max(a['mdd_pct'],100*(a['peak']-equity)/a['peak'])
  wins=sum(t['pnl_usd']>0 for t in a['closed'])
  a.update({'equity_usd':round(equity,4),'net_pnl_usd':round(equity-1000,4),'mdd_pct':round(a['mdd_pct'],3),'closed_count':len(a['closed']),'win_rate_pct':round(wins/len(a['closed'])*100,2) if a['closed'] else None,'open_count':len(a['positions']),'eligible_observed':len(eligible)})
 state.update({'paper_only':True,'real_trading_enabled':False,'updated_at':now,'follower_mode':'IMMEDIATE_CURRENT_POSITION','max_positions_per_category':MAX_POSITIONS,'notional_per_position_usd':NOTIONAL_USD,'limitation':'Eligible whale/trader BTC directions are followed from the first observed current position; no historical PnL/backfill or exchange orders; estimated fees/slippage, funding excluded. Coverage is limited to wallets present in the current public direction feed.'})
 return state

def main():
 state=json.loads(OUT.read_text()) if OUT.exists() else {}
 coh=json.loads((ROOT/'trader-discovery/latest.json').read_text())
 feed=json.loads((ROOT/'data/whale-paper-state.json').read_text())
 now=datetime.datetime.now(datetime.timezone.utc).isoformat()
 OUT.write_text(json.dumps(advance(state,coh,feed,now),indent=2)+'\n')
 print('CATEGORY PAPER PASS')
if __name__=='__main__':main()
