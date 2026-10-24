#!/usr/bin/env python3
"""PC realtime runner for the six 3M KRW / 10X category PAPER ledgers.

Keeps the existing Adaptive PAPER competition intact and physically separates the
six category ledgers into category-paper-realtime.json. Prices are marked every
second; source-driven entry/exit/reversal decisions only run when a genuinely new
trader-position snapshot arrives.
"""
import argparse
import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path

import realtime_runtime as base

ROOT = Path(__file__).resolve().parent
CATEGORY_PATH = ROOT / 'trader-discovery' / 'category_paper.py'
spec = importlib.util.spec_from_file_location('btcflow_category_paper', CATEGORY_PATH)
category = importlib.util.module_from_spec(spec)
spec.loader.exec_module(category)

EXPECTED_KEYS = {f'{cat}_10X' for cat in category.CATS}


def _validate_category_state(state):
    if not state:
        return
    if state.get('paper_only') is not True or state.get('real_trading_enabled') is not False:
        raise ValueError('category runtime must remain PAPER ONLY')
    if state.get('account_count') != 6 or set(state.get('accounts', {})) != EXPECTED_KEYS:
        raise ValueError('category runtime requires exactly six 10X accounts')
    for account in state['accounts'].values():
        if account.get('leverage') != 10 or account.get('starting_equity_krw') != 3000000:
            raise ValueError('category runtime capital/leverage mismatch')


def _blank_category_state(now):
    state = {'accounts': {}}
    category._swing_capital(state, now)
    for account in state['accounts'].values():
        equity = float(account['starting_equity_usd']); fx = float(account['krw_per_usd'])
        account.update(equity_usd=round(equity,4),net_pnl_usd=0.0,unrealized_pnl_usd=0.0,
            margin_used_usd=0.0,free_equity_usd=round(equity,4),total_notional_usd=0.0,
            cost_buffer_usd=0.0,remaining_execution_buffer_usd=0.0,fee_buffer_usd=0.0,
            closed_count=0,win_rate_pct=None,open_count=0,profit_factor=None,closed_pnl_usd=0.0,
            equity_krw=round(equity*fx,2),net_pnl_krw=0.0,margin_used_krw=0.0,
            free_equity_krw=round(equity*fx,2),total_notional_krw=0.0,fee_buffer_krw=0.0,
            cost_buffer_krw=0.0,remaining_execution_buffer_krw=0.0,return_pct=0.0)
    state.update(schema_version=8,paper_only=True,real_trading_enabled=False,updated_at=now,
        follower_mode='COHORT_SPECIFIC_EXECUTION',feed_mode='WAITING_FOR_FIRST_LIVE_SOURCE',
        leverages=[10],account_count=6,observed_wallet_count=0,feed_errors=0,
        max_positions_per_account=category.MAX_POSITIONS,margin_per_position_usd=None,
        maintenance_margin_rate=category.MAINTENANCE_MARGIN_RATE,
        all_accounts_capital_policy={'capital_krw':category.SWING_CAPITAL_KRW,
            'fixed_krw_per_usd':category.SWING_KRW_PER_USD,'capital_epoch':category.SWING_CAPITAL_EPOCH},
        runtime_mode='PC_REALTIME_6_CATEGORY_PAPER_SEPARATE_FROM_ADAPTIVE',runtime_mark_interval_seconds=1,
        runtime_source_refresh_seconds=60,runtime_source_id=None,runtime_source_event=False,
        adaptive_accounts_separate=True,
        control='Six category ledgers are separate from Adaptive PAPER accounts. Waiting for first live source. No real orders.')
    _validate_category_state(state); return state


class CategoryState:
    def __init__(self, adaptive_store):
        db_path = adaptive_store.db.execute('PRAGMA database_list').fetchone()[2]
        self.path = Path(db_path).resolve().parent / 'category-paper-realtime.json'
    def read(self):
        if not self.path.exists(): return {}, None
        payload=json.loads(self.path.read_text(encoding='utf-8'))
        if payload.get('version')!=1: raise ValueError('unsupported category runtime state')
        state=payload.get('state',{}); _validate_category_state(state); return state,payload.get('source_id')
    def save(self,state,source_id):
        _validate_category_state(state); payload={'version':1,'source_id':source_id,'state':state}
        tmp=self.path.with_name(self.path.name+'.tmp')
        with tmp.open('w',encoding='utf-8') as fh:
            json.dump(payload,fh,allow_nan=False,separators=(',',':'));fh.flush();os.fsync(fh.fileno())
        os.replace(tmp,self.path)


def _mark_only(state, price, now):
    state=copy.deepcopy(state)
    if not state:return state
    for account in state.get('accounts',{}).values():
        for wallet,pos in list(account.get('positions',{}).items()):
            liq=pos['liquidation_price'];hit=(pos['side']=='LONG' and price<=liq) or (pos['side']=='SHORT' and price>=liq)
            if hit:
                category._close(account,wallet,pos,price,now,'LIQUIDATION',liq);account['liquidations']=int(account.get('liquidations',0))+1;account.setdefault('pending_reversals',{}).pop(wallet,None)
        positions=account.get('positions',{});unreal=category._unreal(positions,price);equity=account['cash']+unreal
        reserved=sum(p['margin_usd'] for p in positions.values());total_notional=sum(p['notional_usd'] for p in positions.values())
        cost_buffer=sum(category._swing_cost_buffer(p['notional_usd']) for p in positions.values())
        remaining_execution_buffer=sum(category._remaining_execution_buffer(p['notional_usd']) for p in positions.values())
        fee_buffer=sum(p['notional_usd']*2*category.FEE_RATE for p in positions.values())
        account['peak']=max(float(account.get('peak',equity)),equity)
        if account['peak']>0: account['mdd_pct']=max(float(account.get('mdd_pct',0)),100*(account['peak']-equity)/account['peak'])
        closed=account.get('closed',[]);wins=sum(t['pnl_usd']>0 for t in closed);loss=sum(min(0,t['pnl_usd']) for t in closed)
        free_equity=equity-reserved-remaining_execution_buffer
        account.update(equity_usd=round(equity,4),net_pnl_usd=round(equity-account['starting_equity_usd'],4),
            unrealized_pnl_usd=round(unreal,4),margin_used_usd=round(reserved,2),free_equity_usd=round(free_equity,4),
            total_notional_usd=round(total_notional,2),cost_buffer_usd=round(cost_buffer,4),
            remaining_execution_buffer_usd=round(remaining_execution_buffer,4),fee_buffer_usd=round(fee_buffer,4),
            mdd_pct=round(account['mdd_pct'],3),closed_count=len(closed),
            win_rate_pct=round(wins/len(closed)*100,2) if closed else None,open_count=len(positions),
            profit_factor=round(sum(max(0,t['pnl_usd']) for t in closed)/abs(loss),3) if loss else None,
            closed_pnl_usd=round(sum(t['pnl_usd'] for t in closed),4))
        fx=account['krw_per_usd']
        account.update(equity_krw=round(equity*fx,2),net_pnl_krw=round((equity-account['starting_equity_usd'])*fx,2),
            margin_used_krw=round(reserved*fx,2),free_equity_krw=round(free_equity*fx,2),
            total_notional_krw=round(total_notional*fx,2),fee_buffer_krw=round(fee_buffer*fx,2),
            cost_buffer_krw=round(cost_buffer*fx,2),remaining_execution_buffer_krw=round(remaining_execution_buffer*fx,2),
            return_pct=round((equity/account['starting_equity_usd']-1)*100,4))
    state['updated_at']=now;state['runtime_mark_only']=True;return state


class CombinedRunner(base.Runner):
    def __init__(self, store):
        super().__init__(store);self.category_store=CategoryState(store);self.category_state,self.category_source_id=self.category_store.read()
        if not self.category_state:
            self.category_state=_blank_category_state(base.iso(base.time.time()));self.category_store.save(self.category_state,None)
        self.category_source_events=0
    def tick(self,quotes,bundle,now,source_error=None):
        advanced=super().tick(quotes,bundle,now,source_error)
        if not advanced:return False
        source_id=bundle['positions']['generated_at'];feed=copy.deepcopy(bundle['positions']);feed['btc_mid_usd']=quotes.latest['price'];stamp=base.iso(now)
        if source_id!=self.category_source_id:new_category=category.advance(copy.deepcopy(self.category_state),bundle['cohorts'],feed,stamp);source_event=True
        else:new_category=_mark_only(self.category_state,quotes.latest['price'],stamp);source_event=False
        if new_category:
            new_category['runtime_mode']='PC_REALTIME_6_CATEGORY_PAPER_SEPARATE_FROM_ADAPTIVE';new_category['runtime_mark_interval_seconds']=1;new_category['runtime_source_refresh_seconds']=60;new_category['runtime_source_id']=source_id;new_category['runtime_source_event']=source_event;new_category['adaptive_accounts_separate']=True;new_category['control']='Six category ledgers are separate from Adaptive PAPER accounts. No real orders.'
            self.category_store.save(new_category,source_id);self.category_state=new_category
            if source_event:self.category_source_id=source_id;self.category_source_events+=1
        return True
    def public(self,quotes,bundle,now):
        payload=super().public(quotes,bundle,now);state=copy.deepcopy(self.category_state)
        payload.update(category_mode='PC_REALTIME_6_CATEGORY_PAPER_SEPARATE_FROM_ADAPTIVE',category_healthy=bool(payload.get('healthy') and state and self.category_source_id),
            category_source_at=self.category_source_id,category_source_events=self.category_source_events,
            category_account_count=len(state.get('accounts',{})),category_initial_capital_krw=3000000,category_leverage=10,
            category_competition=state,category_rows=[dict(account=key,category=a.get('category'),leverage=a.get('leverage'),
                equity_krw=a.get('equity_krw'),net_pnl_krw=a.get('net_pnl_krw'),return_pct=a.get('return_pct'),
                mdd_pct=a.get('mdd_pct'),free_equity_krw=a.get('free_equity_krw'),liquidations=a.get('liquidations'),
                closed_count=a.get('closed_count')) for key,a in state.get('accounts',{}).items()])
        return payload


def install():base.Runner=CombinedRunner
async def run(args):install();await base.run(args)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--state-dir',required=True);parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8080);parser.add_argument('--share-phone',action='store_true');parser.add_argument('--open-browser',action='store_true');parser.add_argument('--seconds',type=int,default=0);asyncio.run(run(parser.parse_args()))
if __name__=='__main__':main()
