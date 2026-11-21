import unittest

from eth_whale_discovery_v2 import leaderboard_seeds, rank_eth_candidates, eth_fill_profile


class EthWhaleDiscoveryTests(unittest.TestCase):
    def test_leaderboard_seeds_excludes_existing_and_market_makers(self):
        rows = {
            "leaderboardRows": [
                {"ethAddress": "0x" + "1" * 40, "accountValue": "200000",
                 "windowPerformances": [["month", {"pnl": "10000", "vlm": "1000000"}]]},
                {"ethAddress": "0x" + "2" * 40, "accountValue": "200000",
                 "windowPerformances": [["month", {"pnl": "10000", "vlm": "30000000"}]]},
                {"ethAddress": "0x" + "3" * 40, "accountValue": "200000",
                 "windowPerformances": [["month", {"pnl": "10000", "vlm": "1000000"}]]},
            ]
        }
        seeds = leaderboard_seeds(rows, excluded=["0x" + "3" * 40])
        self.assertEqual([x["address"] for x in seeds], ["0x" + "1" * 40])

    def test_eth_profile_uses_eth_closed_pnl_only(self):
        address = "0x" + "1" * 40
        rows = [
            {"coin": "ETH", "time": 100, "tid": 1, "sz": "1", "px": "3000",
             "closedPnl": "20", "dir": "Close Long"},
            {"coin": "BTC", "time": 101, "tid": 2, "sz": "1", "px": "90000",
             "closedPnl": "999", "dir": "Close Long"},
            {"coin": "ETH", "time": 102, "tid": 3, "sz": "1", "px": "3000",
             "closedPnl": "-5", "dir": "Close Short"},
        ]
        profile = eth_fill_profile(
            address, 0, 200, info_fn=lambda _: rows, pause_seconds=0
        )
        self.assertEqual(profile["eth_fill_count"], 2)
        self.assertEqual(profile["eth_close_count"], 2)
        self.assertEqual(profile["eth_realized_pnl_usd"], 15)
        self.assertEqual(profile["eth_win_rate_pct"], 50)

    def test_only_eth_specialists_with_enough_sample_are_selected(self):
        seeds = [{"address": "0x" + str(i) * 40, "leaderboard_month_pnl_usd": 1000}
                 for i in range(1, 4)]
        profiles = {
            seeds[0]["address"]: {"eth_fill_count": 25, "eth_close_count": 10,
                                  "eth_realized_pnl_usd": 200, "eth_win_rate_pct": 60,
                                  "eth_profit_factor": 2.0},
            seeds[1]["address"]: {"eth_fill_count": 25, "eth_close_count": 10,
                                  "eth_realized_pnl_usd": 500, "eth_win_rate_pct": 50,
                                  "eth_profit_factor": 3.0},
            seeds[2]["address"]: {"eth_fill_count": 5, "eth_close_count": 2,
                                  "eth_realized_pnl_usd": 900, "eth_win_rate_pct": 90,
                                  "eth_profit_factor": 5.0},
        }
        selected = rank_eth_candidates(seeds, profiles, 5)
        self.assertEqual([x["address"] for x in selected], [seeds[0]["address"]])


if __name__ == "__main__":
    unittest.main()
