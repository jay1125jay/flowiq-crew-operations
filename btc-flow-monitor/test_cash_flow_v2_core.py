import unittest
from cash_flow_v2_core import new_ledger, apply_wallet_fill, totals, migrate_btc_ledger

W = "0x" + "1"*40

def fill(coin, side, size, before, ms, tid, px):
    return {"coin":coin,"side":side,"sz":str(size),"startPosition":str(before),
            "time":ms,"tid":tid,"px":str(px)}

class CashFlowV2Tests(unittest.TestCase):
    def setUp(self):
        self.ledger = new_ledger([W])

    def test_btc_eth_accounts_are_isolated(self):
        apply_wallet_fill(self.ledger,W,fill("BTC","B",1,0,1000,1,100000),1_000_000)
        self.assertIsNone(self.ledger["wallets"][W]["ETH"]["position"])
        apply_wallet_fill(self.ledger,W,fill("ETH","A",2,0,1001,2,3000),1_000_000)
        self.assertEqual(self.ledger["wallets"][W]["BTC"]["position"]["side"],1)
        self.assertEqual(self.ledger["wallets"][W]["ETH"]["position"]["side"],-1)

    def test_duplicate_fill_is_ignored(self):
        row=fill("BTC","B",1,0,1000,1,100000)
        self.assertEqual(apply_wallet_fill(self.ledger,W,row,1_000_000),"applied")
        self.assertEqual(apply_wallet_fill(self.ledger,W,row,1_000_000),"duplicate")
        self.assertEqual(self.ledger["wallets"][W]["BTC"]["fill_count"],1)

    def test_fee_and_slippage_reduce_long_equity(self):
        row=fill("BTC","B",1,0,1000,1,100000)
        apply_wallet_fill(self.ledger,W,row,1_000_000)
        a=self.ledger["wallets"][W]["BTC"]
        self.assertGreater(a["fees_krw"],0)
        self.assertLess(a["equity_krw"],1_000_000)

    def test_total_is_sum_of_wallet_asset_accounts(self):
        ledger=new_ledger([W,"0x"+"2"*40])
        for wallet, pnl in [(W,10),("0x"+"2"*40,-5)]:
            a=ledger["wallets"][wallet]["BTC"]
            a["equity_krw"] += pnl
        self.assertAlmostEqual(totals(ledger)["net_pnl_krw"],10-5)

    def test_legacy_btc_history_is_preserved(self):
        legacy={"paper_only":True,"real_trading_enabled":False,"initial_krw":1_000_000,
                "leverage":10,"accounts":{W:{"closed":[{"net_krw":123}],"cash":999}}}
        migrated=migrate_btc_ledger(legacy)
        self.assertEqual(migrated["wallets"][W]["BTC"],legacy["accounts"][W])
        self.assertIsNone(migrated["wallets"][W]["ETH"]["position"])

    def test_non_paper_ledger_is_rejected(self):
        ledger=dict(self.ledger,real_trading_enabled=True)
        with self.assertRaises(ValueError):
            totals(ledger)

if __name__ == "__main__":
    unittest.main()
