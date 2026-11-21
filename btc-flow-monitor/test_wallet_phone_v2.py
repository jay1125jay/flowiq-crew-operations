import unittest
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
