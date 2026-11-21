import unittest
import sqlite3
import time
from unittest.mock import patch
from cash_flow_v2_core import new_ledger
from pc_wallet_follow_v2 import V2Observer
from wallet_phone_v2 import V2WalletView


class V2WalletViewTests(unittest.TestCase):
    def test_view_exposes_only_paper_ledger_and_live_state(self):
        view = V2WalletView()
        ledger = {
            "schema_version": 2, "paper_only": True, "real_trading_enabled": False,
            "wallets": {}, "totals": {"net_pnl_krw": 0},
        }
        view.update(ledger, True, 3)
        result = view.read()
        self.assertTrue(result["paper_only"])
        self.assertFalse(result["real_trading_enabled"])
        self.assertTrue(result["pc_live"]["connected"])
        self.assertEqual(result["pc_live"]["pending"], 3)

    def test_observer_orders_same_timestamp_fills_by_source_chain(self):
        wallet = "0x" + "1" * 40
        ledger = new_ledger([wallet])
        account = ledger["wallets"][wallet]["BTC"]
        account.update(initialized=True, source_size=0.0, fill_cursor=0,
                       source_equity_usd=100000)
        stamp = int(time.time() * 1000)
        with patch("pc_wallet_follow_v2.load_ledger", return_value=ledger):
            db = sqlite3.connect(":memory:")
            try:
                observer = V2Observer(db)
                first_received = int(time.time() * 1000)
                late_chain = {"coin":"BTC","side":"B","sz":"0.01","startPosition":"0.01",
                              "time":stamp,"tid":11,"px":"100010"}
                first_chain = {"coin":"BTC","side":"B","sz":"0.01","startPosition":"0",
                               "time":stamp,"tid":10,"px":"100000"}
                with db:
                    db.execute("INSERT INTO pending_v2(wallet,coin,tid,fill_time,payload,received_ms) VALUES(?,?,?,?,?,?)",
                               (wallet,"11",stamp,__import__("json").dumps(late_chain),first_received))
                    db.execute("INSERT INTO pending_v2(wallet,coin,tid,fill_time,payload,received_ms) VALUES(?,?,?,?,?,?)",
                               (wallet,"10",stamp,__import__("json").dumps(first_chain),first_received))
                with patch("pc_wallet_follow_v2.save_ledger"):
                    observer.drain_asset(wallet, "BTC")
                self.assertAlmostEqual(account["source_size"], 0.02)
                self.assertEqual(account["fill_count"], 2)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM pending_v2").fetchone()[0], 0)
            finally:
                db.close()

    def test_read_is_a_snapshot_not_a_mutable_reference(self):
        view = V2WalletView()
        ledger = {"paper_only": True, "real_trading_enabled": False,
                  "wallets": {"0xabc": {"BTC": {"equity_krw": 1}}}}
        view.update(ledger, False, 0)
        result = view.read()
        result["wallets"]["0xabc"]["BTC"]["equity_krw"] = 999
        self.assertEqual(view.read()["wallets"]["0xabc"]["BTC"]["equity_krw"], 1)


if __name__ == "__main__":
    unittest.main()
