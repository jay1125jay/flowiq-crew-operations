"""Offline capture-to-PAPER bridge tests: no external network or account changes."""
import datetime as dt
import unittest

import cloud_capture_paper as bridge

T0 = "2026-11-07T00:00:00+00:00"
T1 = "2026-11-07T00:05:00+00:00"
T2 = "2026-11-07T00:10:00+00:00"
WALLET = "0x" + "1" * 40


def event(at, side="LONG"):
    return {"id": at, "at": at, "btc_mid_usd": 75000,
            "realtime_wallet_observations_only": True, "wallets": {WALLET: side},
            "cohort_wallets": [{"address": WALLET, "category_flags": {"SWING": True}}]}


class CapturePaperTests(unittest.TestCase):
    def test_fresh_event_advances_once_and_preserves_capital(self):
        ledger, applied = bridge.apply_event({}, event(T0))
        self.assertTrue(applied)
        self.assertEqual(ledger["account_count"], 6)
        self.assertEqual(ledger["accounts"]["SWING_10X"]["open_count"], 1)
        self.assertEqual(ledger["observed_source_at"], T0)
        self.assertTrue(ledger["paper_only"])
        self.assertFalse(ledger["real_trading_enabled"])
        other, applied = bridge.apply_event(ledger, event(T0))
        self.assertFalse(applied)
        self.assertIs(other, ledger)
        new, applied = bridge.apply_event(ledger, event(T1, "SHORT"))
        self.assertTrue(applied)
        self.assertEqual(new["accounts"]["SWING_10X"]["open_count"], 1)
        self.assertEqual(new["accounts"]["SWING_10X"]["starting_equity_krw"], 1000000)
        _, applied = bridge.apply_event(new, event(T0))
        self.assertFalse(applied)

    def test_full_engine_newer_state_blocks_rewind(self):
        ledger, _ = bridge.apply_event({}, event(T0))
        ledger["updated_at"] = T2  # a full whale engine run already marked a newer observation
        _, applied = bridge.apply_event(ledger, event(T1))
        self.assertFalse(applied)

    def test_rejects_unverified_or_synthetic_capture(self):
        wrong = event(T0)
        wrong.pop("realtime_wallet_observations_only")
        with self.assertRaisesRegex(ValueError, "UNVERIFIED"):
            bridge.apply_event({}, wrong)
        wrong = event(T0)
        wrong["wallets"] = {}
        with self.assertRaisesRegex(ValueError, "UNOBSERVED"):
            bridge.apply_event({}, wrong)

    def test_never_changes_live_flag(self):
        with self.assertRaisesRegex(ValueError, "LEDGER_MUST_BE_PAPER_ONLY"):
            bridge.apply_event({"paper_only": False}, event(T0))


if __name__ == "__main__":
    unittest.main()
