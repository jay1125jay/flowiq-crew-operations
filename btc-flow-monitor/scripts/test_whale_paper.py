#!/usr/bin/env python3
"""Offline isolated regression test: never writes production PAPER state."""
import copy
import datetime as dt
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = pathlib.Path(__file__).with_name("whale_paper_follow.py")
spec = importlib.util.spec_from_file_location("whale_paper_follow", SCRIPT)
paper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paper)
ADDR = "0x" + "1" * 40

class PaperFlowTest(unittest.TestCase):
    def test_open_close_and_accounting_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            state_file = root / "state.json"
            rank_file = root / "ranking.json"
            rank_file.write_text(json.dumps({
                "status": "OK", "errors": [],
                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "ranked_wallets": [{"address": ADDR, "paper_candidate": True}]
            }))
            ticks = iter([("LONG", 100000), ("SHORT", 101000), ("FLAT", 102000)])
            def fake_api(payload):
                if payload["type"] == "allMids":
                    return {"BTC": str(price[0])}
                return {"assetPositions": [{"position": {"coin": "BTC", "szi": str(size[0])}}]}
            with patch.object(paper, "STATE", state_file), patch.object(paper, "RANK", rank_file), patch.object(paper, "api", side_effect=fake_api):
                # First observation establishes baseline, never opens a position.
                size, price = [1], [100000]
                paper.main()
                a = json.loads(state_file.read_text())
                self.assertEqual(a["closed_trade_count"], 0)
                self.assertEqual(a["open_positions"], 0)
                self.assertAlmostEqual(a["estimated_equity_usd"], 1000)
                # Long -> short must open a short; no fabricated past fill.
                size[0], price[0] = -1, 101000
                paper.main()
                b = json.loads(state_file.read_text())
                self.assertEqual(b["open_positions"], 1)
                self.assertEqual(b["closed_trade_count"], 0)
                self.assertEqual(b["positions"][ADDR]["side"], "SHORT")
                self.assertAlmostEqual(b["cash_usd"], 999.9)
                # Short -> flat closes, including two execution fees and slippage.
                size[0], price[0] = 0, 102000
                paper.main()
                c = json.loads(state_file.read_text())
                self.assertEqual(c["open_positions"], 0)
                self.assertEqual(c["closed_trade_count"], 1)
                t = c["closed_trades"][0]
                self.assertEqual(t["side"], "SHORT")
                self.assertGreater(t["entry_fee_usd"], 0)
                self.assertGreater(t["exit_fee_usd"], 0)
                self.assertAlmostEqual(t["gross_pnl_usd"] - t["entry_fee_usd"] - t["exit_fee_usd"], t["net_pnl_usd"], places=3)
                self.assertAlmostEqual(c["estimated_equity_usd"], 1000 + t["net_pnl_usd"], places=3)
                self.assertAlmostEqual(c["realized_net_pnl_usd"], t["net_pnl_usd"], places=3)
                self.assertTrue(c["paper_only"])
                self.assertEqual(len(c["closed_trades"]), 1)

if __name__ == "__main__":
    unittest.main(verbosity=2)
