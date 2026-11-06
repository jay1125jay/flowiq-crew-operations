"""Regression tests: ranking churn cannot fabricate a trader exit or reset PAPER state."""
import importlib.util
import pathlib
import tempfile
import json
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parent
import category_top6_policy as policy

def module_at(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

category=module_at('btc_test_category_paper',ROOT/'trader-discovery/category_paper.py')
positions=module_at('btc_test_current_positions',ROOT/'trader-discovery/current_positions.py')
A='0x'+'1'*40
B='0x'+'2'*40


class FollowSafetyTests(unittest.TestCase):
    def test_top6_expiry_never_forces_close(self):
        cohort={'paper_only':True,'wallets':[{'address':A,'category_flags':{'WHALE':True}}]}
        feed={'paper_only':True,'btc_mid_usd':70000,'wallets':{A:'LONG'}}
        state=category.advance({},cohort,feed,'2026-11-06T00:00:00+00:00')
        account=state['accounts']['WHALE_10X']
        self.assertIn(A,account['positions'])
        empty={'paper_only':True,'wallets':[]}
        ranked=policy.apply_top6_policy(empty)
        state=policy.rotate_out_non_top6(state,ranked,feed,'2026-11-06T00:05:00+00:00',category)
        self.assertIn(A,account['positions'])
        self.assertEqual(len(account['closed']),0)
        self.assertEqual(state['selection_rotation_deferred_count'],1)

        # Missing score/catalog data never means observed FLAT.
        state=category.advance(state,empty,{'paper_only':True,'btc_mid_usd':70100,'wallets':{}},
                               '2026-11-06T00:10:00+00:00')
        self.assertIn(A,state['accounts']['WHALE_10X']['positions'])
        self.assertEqual(len(state['accounts']['WHALE_10X']['closed']),0)

        # Only the actual exchange state can close the already-held position.
        state=category.advance(state,empty,{
            'paper_only':True,'btc_mid_usd':70200,'wallets':{},'held_wallets':{A:'FLAT'}
        },'2026-11-06T00:15:00+00:00')
        a=state['accounts']['WHALE_10X']
        self.assertNotIn(A,a['positions'])
        self.assertEqual(len(a['closed']),1)
        self.assertEqual(a['closed'][-1]['reason'],'SOURCE_FLAT')

    def test_expired_wallet_is_polled_not_fabricated_flat(self):
        cohort={'paper_only':True,'real_trading_enabled':False,
                'wallets':[{'address':A,'category_flags':{'WHALE':True}}]}
        previous={'catalog_addresses':[A,B]}
        called=[]
        def fake_api(payload):
            called.append(payload)
            if payload['type']=='allMids':
                return {'BTC':'72000'}
            size='1.0' if payload['user']==A else '-2.0'
            return {'assetPositions':[{'position':{'coin':'BTC','szi':size}}]}
        with patch.object(positions,'api',side_effect=fake_api),patch.object(positions.time,'sleep'):
            data=positions.build_observations(cohort,previous,{B})
        self.assertEqual(data['wallets'],{A:'LONG'})
        self.assertEqual(data['held_wallets'],{B:'SHORT'})
        self.assertEqual(data['retired_wallet_count'],1)
        self.assertNotIn(B,data['wallets'])
        self.assertEqual(data['observed_wallet_count'],1)
        self.assertFalse(data['errors'])
        self.assertEqual(len([p for p in called if p['type']=='clearinghouseState']),2)

    def test_local_paper_ledger_held_wallets_are_read_only(self):
        with tempfile.TemporaryDirectory(prefix='btc-flow-safe-') as folder:
            path=pathlib.Path(folder)/'paper.json'
            content={'version':1,'source_id':None,'state':{'paper_only':True,
                     'real_trading_enabled':False,
                     'accounts':{'WHALE_10X':{'positions':{B:{'side':'SHORT'}}}}}}
            path.write_text(json.dumps(content))
            before=path.read_bytes()
            self.assertEqual(positions.held_addresses(path),{B})
            self.assertEqual(before,path.read_bytes())


if __name__=='__main__':
    unittest.main()
