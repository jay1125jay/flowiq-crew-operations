#!/usr/bin/env python3
"""Six trader cohorts x 5x/10x isolated forward-only BTC PAPER ledgers. Never sends orders."""
import json,pathlib,datetime,copy
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'trader-discovery/category-paper.json'
CATS=('WHALE','HIGH_WIN_RATE','HIGH_PROFIT','CONSISTENT','SCALPER','SWING');LEVERAGES=(5,10)
MAX_POSITIONS=6;MARGIN_USD=150.0;SLIPPAGE=0.0003;FEE_RATE=0.0005;MAINTENANCE_MARGIN_RATE=0.005
SWING_CAPITAL_KRW=3000000;SWING_KRW_PER_USD=1500.0
SWING_CAPITAL_EPOCH='ALL_12_ACCOUNTS_KRW_3000000_RESET_V1'
SWING_MIN_HOLD_SECONDS=3600;SWING_REVERSAL_CONFIRMATIONS=2
SWING_COST_BUFFER_RATE=2*(FEE_RATE+SLIPPAGE)

def _liq_price(entry,side,lev):
 move=max(0.0,1/lev-MAINTENANCE_MARGIN_RATE);return entry*(1-move if side=='LONG' else 1+move)
def _unreal(positions,price):
 return sum((price-p['entry'])*p['qty']*(1 if p['side']=='LONG' else -1)-price*p['qty']*FEE_RATE for p in positions.values())
def _age_seconds(stamp,now):
 try:return max(0.0,(datetime.datetime.fromisoformat(now.replace('Z','+00:00'))-datetime.datetime.fromisoformat(stamp.replace('Z','+00:00'))).total_seconds())
 except Exception:return 0.0
def _swing_cost_buffer(notional):return float(notional)*SWING_COST_BUFFER_RATE
def _swing_commitment(p):return float(p['margin_usd'])+float(p.get('cost_buffer_usd',_swing_cost_buffer(p['notional_usd'])))
def _close(a,wallet,p,price,now,reason,exit_override=None):
 exit_price=exit_override if exit_override is not None else price*(1-SLIPPAGE if p['side']=='LONG' else 1+SLIPPAGE)
 gross=(exit_price-p['entry'])*p['qty']*(1 if p['side']=='LONG' else -1);exit_fee=exit_price*p['qty']*FEE_RATE;net=gross-exit_fee-p['entry_fee']
 a['cash']+=gross-exit_fee
 a['closed'].append({'wallet':wallet,'side':p['side'],'leverage':p['leverage'],'entry_price':p['entry'],'exit_price':round(exit_price,6),'liquidation_price':p['liquidation_price'],'entry_at':p.get('entry_at'),'exit_at':now,'margin_usd':p['margin_usd'],'notional_usd':p['notional_usd'],'pnl_usd':round(net,4),'reason':reason})
 a['closed']=a['closed'][-300:];del a['positions'][wallet]
def _new_account(cat,lev):
 initial=SWING_CAPITAL_KRW/SWING_KRW_PER_USD
 return {'category':cat,'leverage':lev,'starting_equity_usd':initial,'cash':initial,'positions':{},'closed':[],'peak':initial,'mdd_pct':0.0,'liquidations':0,'pending_reversals':{},'capital_epoch':SWING_CAPITAL_EPOCH,'started_at':None,'starting_equity_krw':SWING_CAPITAL_KRW,'krw_per_usd':SWING_KRW_PER_USD,'fx_mode':'FIXED_SIMULATION_NOT_LIVE_FX'}

def _swing_capital(state,now):
 for cat in CATS:
  for lev in LEVERAGES:
   key=f'{cat}_{lev}X';old=state['accounts'].get(key)
   if old and old.get('capital_epoch')==SWING_CAPITAL_EPOCH:continue
   if old:
    state.setdefault('capital_archives',[]).append({'account_key':key,'archived_at':now,'reason':'ALL_ACCOUNTS_3000000_KRW_PAPER_RESET','account':copy.deepcopy(old)})
   a=_new_account(cat,lev)
   a.update(started_at=now,allocation_mode='EQUAL_ACROSS_CURRENT_TARGETS_FEE_AND_SLIPPAGE_SAFE',cost_buffer_rate=SWING_COST_BUFFER_RATE)
   state['accounts'][key]=a

def advance(state,coh,feed,now):
 if not coh.get('paper_only') or not feed.get('paper_only') or coh.get('real_trading_enabled') or feed.get('real_trading_enabled'):raise ValueError('paper-only flags required')
 price=float(feed.get('btc_mid_usd') or 0)
 if not 1000<price<1000000:raise ValueError('invalid BTC price')
 signals=feed.get('wallets',{})
 if 'legacy_unleveraged_accounts' not in state and state.get('accounts'):state['legacy_unleveraged_accounts']=state['accounts']
 state['accounts']={k:v for k,v in state.get('accounts',{}).items() if k.endswith('_5X') or k.endswith('_10X')}
 _swing_capital(state,now)
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
    if new=='FLAT':
     if cat=='SWING' and _age_seconds(p.get('entry_at',''),now)<SWING_MIN_HOLD_SECONDS:continue
     _close(a,wallet,p,price,now,'SOURCE_FLAT');a['pending_reversals'].pop(wallet,None)
    elif new!=p['side']:
     if cat=='SWING':
      if _age_seconds(p.get('entry_at',''),now)<SWING_MIN_HOLD_SECONDS:continue
      q=a['pending_reversals'].get(wallet)
      if not q or q.get('side')!=new:a['pending_reversals'][wallet]={'side':new,'count':1,'seen_at':now};continue
      q['count']=int(q.get('count',1))+1
      if q['count']<SWING_REVERSAL_CONFIRMATIONS:continue
      _close(a,wallet,p,price,now,'SWING_REVERSAL_CONFIRMED');a['pending_reversals'].pop(wallet,None);blocked.add(wallet)
     else:
      _close(a,wallet,p,price,now,'SOURCE_FLIP')
      if cat=='WHALE':a['pending_reversals'][wallet]={'side':new,'seen_at':now};blocked.add(wallet)
    elif cat=='SWING':a['pending_reversals'].pop(wallet,None)

   candidates=[w for w in sorted(eligible) if signals.get(w) in ('LONG','SHORT') and w not in blocked and w not in a['positions']]
   candidates=candidates[:max(0,MAX_POSITIONS-len(a['positions']))]
   swing_margin=None
   if candidates:
    cycle_equity=max(0.0,a['cash']+_unreal(a['positions'],price))
    capital_base=min(float(a['starting_equity_usd']),cycle_equity)
    existing_commit=sum(_swing_commitment(p) for p in a['positions'].values())
    remaining_commit=max(0.0,capital_base-existing_commit)
    per_target_commit=remaining_commit/len(candidates)
    swing_margin=per_target_commit/(1+lev*SWING_COST_BUFFER_RATE)
    a['allocation_target_count']=len(a['positions'])+len(candidates)
    a['allocation_capital_usd']=round(capital_base,6)

   for wallet in candidates:
    side=signals.get(wallet)
    if cat=='WHALE' and wallet in a['pending_reversals']:
     pending=a['pending_reversals'][wallet]
     if pending.get('side')!=side:a['pending_reversals'][wallet]={'side':side,'seen_at':now};continue
     a['pending_reversals'].pop(wallet,None)
    margin=swing_margin
    if not margin or margin<=0:continue
    entry=price*(1+SLIPPAGE if side=='LONG' else 1-SLIPPAGE);notional=margin*lev;entry_fee=notional*FEE_RATE
    reserved=sum(p['margin_usd'] for p in a['positions'].values());equity_now=a['cash']+_unreal(a['positions'],price);free_now=equity_now-reserved
    if True:
     existing_commit=sum(_swing_commitment(p) for p in a['positions'].values())
     new_buffer=_swing_cost_buffer(notional)
     capital_base=float(a.get('allocation_capital_usd',a['starting_equity_usd']))
     if existing_commit+margin+new_buffer>capital_base+1e-6:continue
    
    a['cash']-=entry_fee
    pos={'side':side,'leverage':lev,'entry':entry,'qty':notional/entry,'margin_usd':margin,'notional_usd':notional,'entry_fee':entry_fee,'liquidation_price':round(_liq_price(entry,side,lev),6),'entry_at':now,'entry_reason':'WHALE_REVERSAL_CONFIRMED' if cat=='WHALE' else 'SWING_SIGNAL' if cat=='SWING' else 'FOLLOW_CURRENT_OBSERVED_POSITION'}
    if True:
     pos.update(cost_buffer_usd=_swing_cost_buffer(notional),fee_buffer_usd=notional*2*FEE_RATE,slippage_buffer_usd=notional*2*SLIPPAGE)
    a['positions'][wallet]=pos
   for wallet in list(a['pending_reversals']):
    if wallet not in a['positions'] and signals.get(wallet) in (None,'FLAT'):a['pending_reversals'].pop(wallet,None)
   unreal=_unreal(a['positions'],price);equity=a['cash']+unreal;reserved=sum(p['margin_usd'] for p in a['positions'].values());total_notional=sum(p['notional_usd'] for p in a['positions'].values());a['peak']=max(a['peak'],equity);a['mdd_pct']=max(a['mdd_pct'],100*(a['peak']-equity)/a['peak']);wins=sum(t['pnl_usd']>0 for t in a['closed']);loss=sum(min(0,t['pnl_usd']) for t in a['closed'])
   free_equity=equity-reserved
   extra={'total_notional_usd':round(total_notional,2)}
   if True:
    cost_buffer=sum(_swing_cost_buffer(p['notional_usd']) for p in a['positions'].values())
    fee_buffer=sum(p['notional_usd']*2*FEE_RATE for p in a['positions'].values())
    free_equity=equity-reserved-cost_buffer
    extra.update(cost_buffer_usd=round(cost_buffer,4),fee_buffer_usd=round(fee_buffer,4))
   a.update({'equity_usd':round(equity,4),'net_pnl_usd':round(equity-a['starting_equity_usd'],4),'unrealized_pnl_usd':round(unreal,4),'margin_used_usd':round(reserved,2),'free_equity_usd':round(free_equity,4),'mdd_pct':round(a['mdd_pct'],3),'closed_count':len(a['closed']),'win_rate_pct':round(wins/len(a['closed'])*100,2) if a['closed'] else None,'open_count':len(a['positions']),'eligible_observed':len(eligible),'profit_factor':round(sum(max(0,t['pnl_usd']) for t in a['closed'])/abs(loss),3) if loss else None,'closed_pnl_usd':round(sum(t['pnl_usd'] for t in a['closed']),4),**extra})
   if True:
    fx=a['krw_per_usd'];a.update(equity_krw=round(equity*fx,2),net_pnl_krw=round((equity-a['starting_equity_usd'])*fx,2),margin_used_krw=round(reserved*fx,2),total_notional_krw=round(total_notional*fx,2),fee_buffer_krw=round(a['fee_buffer_usd']*fx,2),cost_buffer_krw=round(a['cost_buffer_usd']*fx,2),return_pct=round((equity/a['starting_equity_usd']-1)*100,4))
 state.update({'schema_version':7,'paper_only':True,'real_trading_enabled':False,'updated_at':now,'follower_mode':'COHORT_SPECIFIC_EXECUTION','feed_mode':'FULL_CLASSIFIED_TRADER_CATALOG','leverages':list(LEVERAGES),'account_count':12,'observed_wallet_count':feed.get('observed_wallet_count',len(signals)),'feed_errors':len(feed.get('errors',[])),'max_positions_per_account':MAX_POSITIONS,'margin_per_position_usd':None,'maintenance_margin_rate':MAINTENANCE_MARGIN_RATE,'all_accounts_capital_policy':{'capital_krw':SWING_CAPITAL_KRW,'fixed_krw_per_usd':SWING_KRW_PER_USD,'capital_epoch':SWING_CAPITAL_EPOCH},'swing_capital_policy':{'capital_krw':SWING_CAPITAL_KRW,'fixed_krw_per_usd':SWING_KRW_PER_USD,'allocation':'equal across current entry targets from remaining account capital','cost_buffer_rate':SWING_COST_BUFFER_RATE,'capital_epoch':SWING_CAPITAL_EPOCH},'whale_filter':'Initial WHALE positions follow immediately. After a WHALE source flip, close immediately but require the new direction to persist into the next observation before re-entry.','swing_filter':f'SWING holds positions for at least {SWING_MIN_HOLD_SECONDS//60} minutes unless liquidation. After minimum hold, an opposite signal must persist for {SWING_REVERSAL_CONFIRMATIONS} observations before exit; no same-cycle reverse entry.','limitation':'PAPER only. 5x/10x isolated-style simulations; fixed test FX KRW 1500 per USD for SWING display only; sampled mark liquidation approximation; funding not modeled; no same-cycle re-entry after liquidation; no real orders.'});return state

def main():
 state=json.loads(OUT.read_text()) if OUT.exists() else {};coh=json.loads((ROOT/'trader-discovery/latest.json').read_text());feed=json.loads((ROOT/'trader-discovery/current-positions.json').read_text());now=datetime.datetime.now(datetime.timezone.utc).isoformat();OUT.write_text(json.dumps(advance(state,coh,feed,now),indent=2)+'\n');print('CATEGORY PAPER PASS 12 accounts 5x/10x',feed.get('observed_wallet_count'))
if __name__=='__main__':main()
