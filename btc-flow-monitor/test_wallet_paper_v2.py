import unittest
import time
import json
from unittest.mock import patch

import wallet_paper_v2 as paper
from cash_flow_v2_core import new_ledger


W = "0x" + "1" * 40


def state_fixture():
    return {
        "time": int(time.time() * 1000),
        "marginSummary": {"accountValue": "100000"},
        "assetPositions": [
            {"position": {"coin": "BTC", "szi": "0.01", "entryPx": "100000"}},
            {"position": {"coin": "ETH", "szi": "-0.5", "entryPx": "3000"}},
        ],
    }


def book(coin, bid, ask):
    return {"coin": coin, "time": int(time.time() * 1000),
            "levels": [[{"px": str(bid)}], [{"px": str(ask)}]]}


class WalletPaperV2Tests(unittest.TestCase):
    def test_reconcile_initializes_btc_and_eth_independently(self):
        ledger = new_ledger([W])
        responses = [state_fixture(), book("BTC", 100000, 100010), book("ETH", 3000, 3001)]
        with patch.object(paper, "info", side_effect=responses):
            result = paper.reconcile_wallet(ledger, W)
        btc = ledger["wallets"][W]["BTC"]
        eth = ledger["wallets"][W]["ETH"]
        self.assertTrue(btc["initialized"])
        self.assertTrue(eth["initialized"])
        self.assertEqual(btc["source_size"], 0.01)
        self.assertEqual(eth["source_size"], -0.5)
        self.assertEqual(btc["position"]["side"], 1)
        self.assertEqual(eth["position"]["side"], -1)
        self.assertEqual(btc["source_side"], "LONG")
        self.assertEqual(eth["source_side"], "SHORT")
        self.assertIn("BTC", result)
        self.assertIn("ETH", result)

    def test_same_timestamp_fill_chain_applies_in_source_order(self):
        ledger = new_ledger([W])
        account = ledger["wallets"][W]["BTC"]
        account.update(initialized=True, source_size=0.0, fill_cursor=0, source_equity_usd=100000)
        stamp = int(time.time() * 1000)
        rows = [
            {"coin":"BTC","side":"B","sz":"0.01","startPosition":"0","time":stamp,"tid":10,"px":"100000"},
            {"coin":"BTC","side":"B","sz":"0.01","startPosition":"0.01","time":stamp,"tid":11,"px":"100010"},
        ]
        result = paper.apply_ordered_coin(ledger, W, "BTC", rows, 100000, stamp)
        self.assertEqual(result, "fills_applied")
        self.assertAlmostEqual(account["source_size"], 0.02)
        self.assertEqual(account["fill_count"], 2)
        self.assertIsNone(ledger["wallets"][W]["ETH"]["position"])

    def test_source_gap_is_held_not_guessed(self):
        ledger = new_ledger([W])
        account = ledger["wallets"][W]["ETH"]
        account.update(initialized=True, source_size=0.0, fill_cursor=0)
        stamp = int(time.time() * 1000)
        rows = [{"coin":"ETH","side":"B","sz":"0.5","startPosition":"0.25",
                 "time":stamp,"tid":99,"px":"3000"}]
        with self.assertRaisesRegex(ValueError, "ETH source fill chain mismatch"):
            paper.apply_ordered_coin(ledger, W, "ETH", rows, 100000, stamp)
        self.assertEqual(account["source_size"], 0.0)
        self.assertIsNone(account["position"])

    def test_first_v2_load_migrates_latest_main_btc_ledger(self):
        legacy = {
            "paper_only": True, "real_trading_enabled": False,
            "initial_krw": 1_000_000, "leverage": 10,
            "accounts": {W: {"cash": 950000, "equity_krw": 960000,
                            "fill_cursor": 1000, "source_size": 0.01,
                            "closed": []}},
        }
        with patch.object(paper, "OUT") as out:
            out.exists.return_value = False
            with patch.object(paper, "latest_main_text", return_value=json.dumps(legacy)):
                migrated = paper.load_ledger([W])
        self.assertEqual(migrated["wallets"][W]["BTC"]["cash_krw"], 950000)
        self.assertTrue(migrated["wallets"][W]["BTC"]["initialized"])
        self.assertFalse(migrated["wallets"][W]["BTC"]["fees_history_complete"])
        self.assertFalse(migrated["legacy_btc_snapshot"][W] is None)

    def test_aged_source_gap_closes_only_the_verified_reduced_fraction(self):
        wallet = W
        stamp = int(time.time() * 1000)
        state = {
            "time": stamp, "marginSummary": {"accountValue": "100000"},
            "assetPositions": [
                {"position": {"coin": "BTC", "szi": "0.005", "entryPx": "100000"}}
            ],
        }
        ledger = new_ledger([wallet])
        btc = ledger["wallets"][wallet]["BTC"]
        btc.update(initialized=True, source_size=0.01, fill_cursor=stamp-600000,
                   source_equity_usd=100000, cash_krw=995000, equity_krw=995000,
                   position={"side":1,"entry_price":100000,"notional_krw":10000000,
                             "entry_fee_krw":5000,"opened_at":"2026-11-21T00:00:00+00:00"})
        missing_chain = {"coin":"BTC","side":"A","sz":"0.004","startPosition":"0.009",
                         "time":stamp-500000,"tid":77,"px":"99990"}
        responses = [state, book("BTC", 99990, 100000), book("ETH", 3000, 3001)]
        with patch.object(paper, "info", side_effect=responses), patch.object(
            paper, "fetch_fills", return_value=[missing_chain]
        ):
            result = paper.reconcile_wallet(ledger, wallet)
        btc = ledger["wallets"][wallet]["BTC"]
        self.assertEqual(result["BTC"], "snapshot_gap_recovered")
        self.assertAlmostEqual(btc["source_size"], 0.005)
        self.assertAlmostEqual(btc["position"]["notional_krw"], 5_000_000)
        self.assertEqual(btc["closed"][-1]["reason"], "snapshot_gap_recovery")
        self.assertEqual(btc["fill_cursor"], stamp)
        self.assertTrue(btc["history_gap_at"])

    def test_empty_latest_main_ledger_aborts_migration(self):
        with patch.object(paper, "OUT") as out:
            out.exists.return_value = False
            with patch.object(paper, "latest_main_text", return_value=""):
                with self.assertRaisesRegex(ValueError, "ledger is empty"):
                    paper.load_ledger([W])

    def test_bad_or_stale_order_book_is_rejected(self):
        ledger = new_ledger([W])
        responses = [state_fixture(), book("BTC", 100000, 100010), book("WRONG", 3000, 3001)]
        with patch.object(paper, "info", side_effect=responses):
            with self.assertRaisesRegex(ValueError, "ETH invalid order book"):
                paper.reconcile_wallet(ledger, W)


if __name__ == "__main__":
    unittest.main()
