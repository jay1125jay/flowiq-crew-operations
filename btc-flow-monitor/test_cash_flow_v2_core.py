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

    def test_multiple_fills_with_same_timestamp_are_processed(self):
        first=fill("BTC","B",1,0,1000,1,100000)
        second=fill("BTC","B",1,1,1000,2,100100)
        self.assertEqual(apply_wallet_fill(self.ledger,W,first,1_000_000),"applied")
        self.assertEqual(apply_wallet_fill(self.ledger,W,second,1_000_000),"applied")
        self.assertEqual(self.ledger["wallets"][W]["BTC"]["fill_count"],2)

    def test_fee_and_slippage_reduce_long_equity(self):
        row=fill("BTC","B",1,0,1000,1,100000)
        apply_wallet_fill(self.ledger,W,row,1_000_000)
        a=self.ledger["wallets"][W]["BTC"]
        self.assertGreater(a["fees_krw"],0)
        self.assertLess(a["equity_krw"],1_000_000)

    def test_long_close_records_net_pnl_after_both_fees(self):
        open_row=fill("BTC","B",1,0,1000,1,100000)
        close_row=fill("BTC","A",1,1,2000,2,101000)
        apply_wallet_fill(self.ledger,W,open_row,1_000_000)
        apply_wallet_fill(self.ledger,W,close_row,1_000_000)
        a=self.ledger["wallets"][W]["BTC"]
        self.assertIsNone(a["position"])
        self.assertGreater(a["closed"][-1]["net_pnl_krw"],0)
        self.assertGreater(a["closed"][-1]["entry_fee_krw"],0)
        self.assertGreater(a["closed"][-1]["exit_fee_krw"],0)

    def test_liquidation_is_recorded_in_paper_account(self):
        open_row=fill("BTC","B",1,0,1000,1,100000)
        apply_wallet_fill(self.ledger,W,open_row,1_000_000)
        a=self.ledger["wallets"][W]["BTC"]
        from cash_flow_v2_core import mark_account
        mark_account(a,89000,"test-liquidation")
        self.assertIsNone(a["position"])
        self.assertEqual(a["closed"][-1]["reason"],"liquidation")

    def test_total_is_sum_of_wallet_asset_accounts(self):
        ledger=new_ledger([W,"0x"+"2"*40])
        for wallet, pnl in [(W,10),("0x"+"2"*40,-5)]:
            a=ledger["wallets"][wallet]["BTC"]
            a["equity_krw"] += pnl
        self.assertAlmostEqual(totals(ledger)["net_pnl_krw"],10-5)

    def test_legacy_btc_history_is_preserved(self):
        legacy={"paper_only":True,"real_trading_enabled":False,"initial_krw":1_000_000,
                "leverage":10,"accounts":{W:{"closed":[{"net_krw":123}],"cash":999}}}
        legacy["accounts"][W].update(fill_cursor=1234,source_size=0.25,price=98000,last_at="2026-11-20T00:00:00+00:00")
        migrated=migrate_btc_ledger(legacy)
        btc=migrated["wallets"][W]["BTC"]
        self.assertEqual(btc["cash_krw"],999)
        self.assertEqual(btc["fill_cursor"],1234)
        self.assertEqual(btc["source_size"],0.25)
        self.assertEqual(migrated["legacy_btc_snapshot"][W],legacy["accounts"][W])
        self.assertIsNone(migrated["wallets"][W]["ETH"]["position"])
        self.assertAlmostEqual(totals(migrated)["initial_krw"],2_000_000)

    def test_non_paper_ledger_is_rejected(self):
        ledger=dict(self.ledger,real_trading_enabled=True)
        with self.assertRaises(ValueError):
            totals(ledger)

if __name__ == "__main__":
    unittest.main()
