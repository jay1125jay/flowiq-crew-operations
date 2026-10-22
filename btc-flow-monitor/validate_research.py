#!/usr/bin/env python3
"""Fail closed before ledger execution and before publication."""
import datetime as dt
import json
import sys
from adaptive_meta import ROOT, ENGINES, safe, fresh, validate_inputs, number

def validate(outputs=False):
    def read(p): return json.loads((ROOT/p).read_text())
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    coh=read('trader-discovery/latest.json'); feed=read('trader-discovery/current-positions.json')
    validate_inputs(coh,feed,read('data/adaptive-market.json'),read('data/whale-ranking.json'),now)
    if outputs:
        p=read('trader-discovery/category-paper.json'); m=read('data/adaptive-meta.json')
        safe(p);safe(m)
        fresh(p['updated_at'],now);fresh(m['updated_at'],now)
        expected={f'{c}_{l}X' for c in ('WHALE','HIGH_WIN_RATE','HIGH_PROFIT','CONSISTENT','SCALPER','SWING') for l in (5,10)}
        assert p['schema_version']==7 and set(p['accounts'])==expected and p['account_count']==12
        assert p['paper_only'] is True and p['real_trading_enabled'] is False
        assert p['feed_errors']==0 and p['observed_wallet_count']==len(feed['wallets'])
        policy=p['all_accounts_capital_policy']
        assert policy['capital_krw']==3000000 and policy['fixed_krw_per_usd']==1500
        for key,account in p['accounts'].items():
            assert account['starting_equity_krw']==3000000 and account['starting_equity_usd']==2000
            assert account['capital_epoch']==policy['capital_epoch']
            assert account['krw_per_usd']==1500 and account['fx_mode']=='FIXED_SIMULATION_NOT_LIVE_FX'
            assert account['margin_used_krw']+account['cost_buffer_krw']<=3000000.1
        for leverage,target_notional in ((5,15000000),(10,30000000)):
            a=p['accounts'][f'SWING_{leverage}X']
            assert a['starting_equity_krw']==3000000 and a['starting_equity_usd']==2000
            assert a['krw_per_usd']==1500 and a['fx_mode']=='FIXED_SIMULATION_NOT_LIVE_FX'
            assert a['capital_epoch']==policy['capital_epoch']
            assert a['allocation_mode']=='EQUAL_ACROSS_CURRENT_TARGETS_FEE_AND_SLIPPAGE_SAFE'
            assert a['margin_used_krw']+a['cost_buffer_krw']<=3000000.10
            assert 0<=a['total_notional_krw']<=target_notional+0.10
            assert abs(a['net_pnl_usd']-(a['equity_usd']-a['starting_equity_usd']))<0.0002
            assert abs(a['equity_krw']-a['equity_usd']*1500)<0.2
            margins=[x['margin_usd'] for x in a['positions'].values()]
            if len(margins)>1 and len(margins)==a.get('allocation_target_count'):
                assert max(margins)-min(margins)<1e-8
        assert m['schema_version']==3 and set(m['accounts'])==set(ENGINES)
        assert set(m['decisions'])==set(ENGINES) and len(m['leaderboard'])==6
        assert m['last_observation_at']==feed['generated_at'] and m['data_quality']['feed_errors']==0
        assert abs(sum(m['engine_weights'].values())-1)<1e-9
        assert m['paper_rules']['starting_equity_usd']==1000 and m['paper_rules']['max_notional_usd']==500
        for a in m['accounts'].values():
            assert a['closed_count']==len(a['closed'])
            for key in ('cash','equity_usd','mdd_pct','fees_usd','expectancy_usd'): number(a[key])
            assert abs(a['cash']-(1000+sum(t['pnl_usd'] for t in a['closed'])-sum(p['entry_fee']+p['funding_usd'] for p in a['positions'].values())))<1e-6
        whale=read('data/whale-paper-state.json')
        assert whale['paper_only'] is True and not whale.get('real_trading_enabled',False)
        fresh(whale['updated_at'],now)
        assert set(whale['leverage_accounts'])=={'2','5','10'}
    print('RESEARCH SAFETY / FRESHNESS / FEED / ACCOUNTS PASS', 'outputs' if outputs else 'inputs')

if __name__=='__main__': validate('--outputs' in sys.argv)
