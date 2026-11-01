import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
CATEGORY_PATH = ROOT / "trader-discovery" / "category_paper.py"
SPEC = importlib.util.spec_from_file_location("btcflow_category_paper_contract", CATEGORY_PATH)
category = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(category)

ADDR = "0x" + "1" * 40


class PaperAccountContractTests(unittest.TestCase):
    def test_six_accounts_are_paper_only_three_million_krw_and_10x(self):
        flags = {name: True for name in category.CATS}
        cohorts = {
            "paper_only": True,
            "real_trading_enabled": False,
            "wallets": [{"address": ADDR, "category_flags": flags}],
        }
        positions = {
            "paper_only": True,
            "real_trading_enabled": False,
            "btc_mid_usd": 50000,
            "wallets": {ADDR: "LONG"},
        }

        state = category.advance({}, cohorts, positions, "2026-11-01T00:00:00+00:00")

        expected = {f"{name}_10X" for name in category.CATS}
        self.assertIs(state["paper_only"], True)
        self.assertIs(state["real_trading_enabled"], False)
        self.assertEqual(state["account_count"], 6)
        self.assertEqual(set(state["accounts"]), expected)
        self.assertEqual(category.MAX_POSITIONS, 6)
        self.assertEqual(state["max_positions_per_account"], category.MAX_POSITIONS)

        for account in state["accounts"].values():
            self.assertEqual(account["starting_equity_krw"], 3000000)
            self.assertEqual(account["leverage"], 10)
            self.assertLessEqual(account["open_count"], category.MAX_POSITIONS)
            self.assertGreater(account["total_notional_krw"], 29500000)
            self.assertLess(account["total_notional_krw"], 30000000)


if __name__ == "__main__":
    unittest.main()
