#!/usr/bin/env python3
"""Offline isolated regression tests. Never writes production PAPER state."""
import datetime as dt, importlib.util, json, pathlib, tempfile, unittest
from unittest.mock import patch
SCRIPT=pathlib.Path(__file__).with_name("whale_paper_follow.py"); spec=importlib.util.spec_from_file_location("whale_paper_follow",SCRIPT); paper=importlib.util.module_from_spec(spec); spec.loader.exec_module(paper)
ADDR="0x"+"1"*40
class PaperFlowTest(unittest.TestCase):
 def test_leverage_and_risk_model(self):
  self.assertAlmostEqual(paper.liquid_price(100000,"LONG",10),90500); self.assertAlmostEqual(paper.liquid_price(100000,"SHORT",10),109500); self.assertEqual(paper.BASE_MARGIN_USD,200.0); self.assertEqual(paper.MAX_POSITIONS,3); self.assertEqual(paper.MAX_MARGIN_USAGE_PCT,0.60); s={"leverage_accounts":{"1":{"leverage":1}}}; a=paper.init_accounts(s); self.assertEqual(set(a),set(str(i) for i in range(2,11))); self.assertNotIn("1",a); self.assertEqual(a["10"]["cash_usd"],1000)
 def test_open_close_independent_accounts(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp); state=root/"state.json"; rank=root/"ranking.json"; rank.write_text(json.dumps({"status":"OK","errors":[],"updated_at":dt.datetime.now(dt.timezone.utc).isoformat(),"ranked_wallets":[{"address":ADDR,"paper_candidate":True}]}))
   def fake_api(payload):
    if payload["type"]=="allMids":return {"BTC":str(price[0])}
    return {"assetPositions":[{"position":{"coin":"BTC","szi":str(size[0])}}]}
   with patch.object(paper,"STATE",state),patch.object(paper,"RANK",rank),patch.object(paper,"api",side_effect=fake_api):
    size,price=[1],[100000]; paper.main(); a=json.loads(state.read_text()); self.assertEqual(a["open_positions"],0); self.assertNotIn("leverage_tests",a); self.assertEqual(len(a["leverage_accounts"]),9); self.assertNotIn("1",a["leverage_accounts"])
    size[0],price[0]=-1,101000; paper.main(); b=json.loads(state.read_text()); self.assertEqual(b["leverage_accounts"]["2"]["open_positions"],1); self.assertEqual(b["leverage_accounts"]["10"]["open_positions"],1); self.assertAlmostEqual(b["leverage_accounts"]["2"]["margin_used_usd"],200); self.assertAlmostEqual(b["leverage_accounts"]["10"]["positions"][ADDR]["notional_usd"],2000)
    size[0],price[0]=0,102000; paper.main(); c=json.loads(state.read_text()); self.assertEqual(c["leverage_accounts"]["2"]["closed_trade_count"],1); self.assertEqual(c["leverage_accounts"]["10"]["closed_trade_count"],1); self.assertNotEqual(c["leverage_accounts"]["2"]["realized_net_pnl_usd"],c["leverage_accounts"]["10"]["realized_net_pnl_usd"]); self.assertTrue(c["paper_only"])
if __name__=="__main__":unittest.main(verbosity=2)
