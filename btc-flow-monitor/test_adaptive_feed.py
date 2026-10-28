import unittest
from adaptive_feed import current_catalog_feed

A='0x'+'1'*40
B='0x'+'2'*40

class AdaptiveFeedTests(unittest.TestCase):
    def test_retired_flat_is_excluded_from_strict_adaptive_feed(self):
        coh={'wallets':[{'address':A}]}
        raw={'wallets':{A:'LONG',B:'FLAT'},'catalog_wallet_count':1,'observed_wallet_count':1,'retired_wallet_count':1}
        out=current_catalog_feed(coh,raw)
        self.assertEqual(out['wallets'],{A:'LONG'})
        self.assertEqual(out['catalog_wallet_count'],1)
        self.assertEqual(out['observed_wallet_count'],1)
        self.assertEqual(raw['wallets'][B],'FLAT')

    def test_missing_current_wallet_stays_detectable(self):
        coh={'wallets':[{'address':A},{'address':B}]}
        raw={'wallets':{A:'LONG'},'catalog_wallet_count':2,'observed_wallet_count':1}
        out=current_catalog_feed(coh,raw)
        self.assertEqual(out['catalog_wallet_count'],2)
        self.assertEqual(out['observed_wallet_count'],1)
        self.assertNotEqual(len(out['wallets']),out['catalog_wallet_count'])

if __name__=='__main__':unittest.main()
