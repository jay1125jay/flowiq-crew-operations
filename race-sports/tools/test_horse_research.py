import copy
import unittest
import horse_win_confidence_roi as c
import validate_horse_model as hv

class ResearchSafety(unittest.TestCase):
    def races(self):
        return [{'id':str(i),'event_date':f'2020-{i//28+1:02d}-{i%28+1:02d}',
                 'outcomes':[{'horse_name':'A','jockey':'J','trainer':'T','final_rank':1,'final_odds':2},
                             {'horse_name':'B','jockey':'K','trainer':'U','final_rank':2,'final_odds':3}]} for i in range(140)]
    def test_same_date_cannot_train_other_race(self):
        races=self.races();races[120]['event_date']=races[119]['event_date']
        before=list(hv.walk_forward_predictions(races))
        changed=copy.deepcopy(races);changed[119]['outcomes'][0]['final_rank']=2;changed[119]['outcomes'][1]['final_rank']=1
        after=list(hv.walk_forward_predictions(changed))
        self.assertEqual(before[120][1],after[120][1])
        self.assertNotEqual(before[121][1],after[121][1])
    def test_odds_only_affect_settlement(self):
        races=self.races();a=c.build_rows(races)[2]
        changed=copy.deepcopy(races)
        for e in changed:
            for o in e['outcomes']:o['final_odds']=None
        b=c.build_rows(changed)[2]
        self.assertEqual([(x['event_id'],x['top_p'],x['margin']) for x in a],[(x['event_id'],x['top_p'],x['margin']) for x in b])
        self.assertEqual(c.metric(a,0)['bets'],c.metric(b,0)['bets'])
        self.assertEqual(c.metric(b,0)['roi_bets'],0)
        self.assertIsNone(c.metric(b,0)['roi'])
    def test_split_no_shared_date(self):
        rows=[{'event_date':str(i//3)} for i in range(20)]
        a,b=c.split_rows(rows);self.assertNotEqual(a[-1]['event_date'],b[0]['event_date'])
    def test_no_false_positive_or_small_sample(self):
        d={'roi_bets':150,'roi':-.1};h={'roi_bets':75,'roi':.1}
        self.assertEqual(c.state(d,h),'FAIL')
        self.assertEqual(c.state(d,{'roi_bets':74,'roi':.5}),'HOLD_SMALL_SAMPLE')
        d['roi']=.1;self.assertEqual(c.state(d,h),'HOLD_REUSED_HISTORICAL_HOLDOUT')
    def test_grid_fixed_and_nonfinite_odds_excluded(self):
        self.assertEqual(c.p_grid([]),c.p_grid([{'top_p':.999}]))
        rows=[{'top_p':.2,'margin':.1,'hit':True,'odds':float('inf')}]
        self.assertEqual(c.metric(rows,.1)['roi_bets'],0)
if __name__=='__main__':unittest.main()
