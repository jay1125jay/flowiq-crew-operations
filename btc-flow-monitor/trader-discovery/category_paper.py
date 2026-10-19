#!/usr/bin/env python3
"""Six trader cohorts x 5x/10x isolated forward-only BTC PAPER ledgers. Never sends orders."""
import json,pathlib,datetime
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'trader-discovery/category-paper.json'
CATS=('WHALE','HIGH_WIN_RATE','HIGH_PROFIT','CONSISTENT','SCALPER','SWING');LEVERAGES=(5,10)
MAX_POSITIONS=6;MARGIN_USD=150.0;SLIPPAGE=0.0003;FEE_RATE=0.0005;MAINTENANCE_MARGIN_RATE=0.005

def _liq_price(entry,side,lev):
 move=max(0.0,1/lev-MAINTENANCE_MARGIN_RATE);return entry*(1-move if side=='LONG' else 1+move)
def _unreal(positions,price):
 return sum((price-p['entry'])*p['qty']*(1 if p['side']=='LONG' else -1)-price*p['qty']*FEE_RATE for p in positions.values())
def _close(a,wallet,p,price,now,reason,exit_override=None):
 exit_price=exit_override if exit_override is not None else price*(1-SLIPPAGE if p['side']=='LONG' else 1+SLIPPAGE)
 gross=(exit_price-p['entry'])*p['qty']*(1 if p['side']=='LONG' else -1);exit_fee=exit_price*p['qty']*FEE_RATE;net=gross-exit_fee-p['entry_fee']
 a['cash']+=gross-exit_fee
 a['closed'].append({'wallet':wallet,'side':p['side'],'leverage':p['leverage'],'entry_price':p['entry'],'exit_price':round(exit_price,6),'liquidation_price':p['liquidation_price'],'entry_at':p.get('entry_at'),'exit_at':now,'margin_usd':p['margin_usd'],'notional_usd':p['notional_usd'],'pnl_usd':round(net,4),'reason':reason})
 a['closed']=a['closed'][-300:];del a['positions'][wallet]
def _new_account(cat,lev):return {'category':cat,'leverage':lev,'starting_equity_usd':1000.0,'cash':1000.0,'positions':{},'closed':[],'peak':1000.0,'mdd_pct':0.0,'liquidations':0,'pending_reversals':{}}

def advance(state,coh,feed,now):
 if not coh.get('paper_only') or not feed.get('paper_only') or coh.get('real_trading_enabled') or feed.get('real_trading_enabled'):raise ValueError('paper-only flags required')
 price=float(feed.get('btc_mid_usd') or 0)
 if not 1000<price<1000000:raise ValueError('invalid BTC price')
 signals=feed.get('wallets',{})
 if 'legacy_unleveraged_accounts' not in state and state.get('accounts'):state['legacy_unleveraged_accounts']=state['accounts']
 state['accounts']={k:v for k,v in state.get('accounts',{}).items() if k.endswith('_5X') or k.endswith('_10X')}
 for cat in CATS:
  eligible={w['address'] for w in coh.get('wallets',[]) if w.get('category_flags',{}).get(cat) and w.get('address') in signals}
  for lev in LEVERAGES:
   key=f'{cat}_{lev}X';a=state['accounts'].setdefault(key,_new_account(cat,lev));a.setdefault('pending_reversals',{});blocked=set()
   for wallet,p in list(a['positions'].items()):
    liq=p['liquidation_price'];hit=(p['side']=='LONG' and price<=liq) or (p['side']=='SHORT' and price>=liq)
    if hit:
     _close(a,wallet,p,price,now,'LIQUIDATION',liq);a['liquidations']+=1;blocked.add(wallet);a['pending_reversals'].pop(wallet,None);continue
    if wallet not in signals:continue
    new=signals.get(wallet)
    if new=='FLAT':_close(a,wallet,p,price,now,'SOURCE_FLAT');a['pending_reversals'].pop(wallet,None)
    elif new!=p['side']:
     _close(a,wallet,p,price,now,'SOURCE_FLIP')
     if cat=='WHALE':a['pending_reversals'][wallet]={'side':new,'seen_at':now};blocked.add(wallet)
   for wallet in sorted(eligible):
    side=signals.get(wallet)
    if side not in ('LONG','SHORT') or wallet in blocked or wallet in a['positions'] or len(a['positions'])>=MAX_POSITIONS:continue
    if cat=='WHALE' and wallet in a['pending_reversals']:
     pending=a['pending_reversals'][wallet]
     if pending.get('side')!=side:a['pending_reversals'][wallet]={'side':side,'seen_at':now};continue
     a['pending_reversals'].pop(wallet,None)
    entry=price*(1+SLIPPAGE if side=='LONG' else 1-SLIPPAGE);notional=MARGIN_USD*lev;entry_fee=notional*FEE_RATE
    reserved=sum(p['margin_usd'] for p in a['positions'].values());equity_now=a['cash']+_unreal(a['positions'],price);free_now=equity_now-reserved
    if free_now < MARGIN_USD+entry_fee:continue
    a['cash']-=entry_fee;a['positions'][wallet]={'side':side,'leverage':lev,'entry':entry,'qty':notional/entry,'margin_usd':MARGIN_USD,'notional_usd':notional,'entry_fee':entry_fee,'liquidation_price':round(_liq_price(entry,side,lev),6),'entry_at':now,'entry_reason':'WHALE_REVERSAL_CONFIRMED' if cat=='WHALE' else 'FOLLOW_CURRENT_OBSERVED_POSITION'}
   for wallet in list(a['pending_reversals']):
    if signals.get(wallet) in (None,'FLAT'):a['pending_reversals'].pop(wallet,None)
   unreal=_unreal(a['positions'],price);equity=a['cash']+unreal;reserved=sum(p['margin_usd'] for p in a['positions'].values());a['peak']=max(a['peak'],equity);a['mdd_pct']=max(a['mdd_pct'],100*(a['peak']-equity)/a['peak']);wins=sum(t['pnl_usd']>0 for t in a['closed']);loss=sum(min(0,t['pnl_usd']) for t in a['closed'])
   a.update({'equity_usd':round(equity,4),'net_pnl_usd':round(equity-1000,4),'unrealized_pnl_usd':round(unreal,4),'margin_used_usd':round(reserved,2),'free_equity_usd':round(equity-reserved,4),'mdd_pct':round(a['mdd_pct'],3),'closed_count':len(a['closed']),'win_rate_pct':round(wins/len(a['closed'])*100,2) if a['closed'] else None,'open_count':len(a['positions']),'eligible_observed':len(eligible),'profit_factor':round(sum(max(0,t['pnl_usd']) for t in a['closed'])/abs(loss),3) if loss else None,'closed_pnl_usd':round(sum(t['pnl_usd'] for t in a['closed']),4)})
 state.update({'schema_version':5,'paper_only':True,'real_trading_enabled':False,'updated_at':now,'follower_mode':'IMMEDIATE_CURRENT_POSITION_WITH_WHALE_REVERSAL_CONFIRMATION','feed_mode':'FULL_CLASSIFIED_TRADER_CATALOG','leverages':list(LEVERAGES),'account_count':12,'observed_wallet_count':feed.get('observed_wallet_count',len(signals)),'feed_errors':len(feed.get('errors',[])),'max_positions_per_account':MAX_POSITIONS,'margin_per_position_usd':MARGIN_USD,'maintenance_margin_rate':MAINTENANCE_MARGIN_RATE,'whale_filter':'Initial WHALE positions follow immediately. After a WHALE source flip, close immediately but require the new direction to persist into the next observation before re-entry. Other cohorts retain immediate flip behavior.','limitation':'PAPER only. 5x/10x isolated-style simulations; sampled mark liquidation approximation; funding not modeled; no same-cycle re-entry after liquidation; no real orders.'});return state

def main():
 state=json.loads(OUT.read_text()) if OUT.exists() else {};coh=json.loads((ROOT/'trader-discovery/latest.json').read_text());feed=json.loads((ROOT/'trader-discovery/current-positions.json').read_text());now=datetime.datetime.now(datetime.timezone.utc).isoformat();OUT.write_text(json.dumps(advance(state,coh,feed,now),indent=2)+'\n');print('CATEGORY PAPER PASS 12 accounts 5x/10x',feed.get('observed_wallet_count'))
if __name__=='__main__':main()
