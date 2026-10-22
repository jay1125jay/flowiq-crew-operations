import copy
import unittest
from datetime import datetime, timezone, timedelta
from sports_pending_results import summary_url, final_event, recover_pending
from sports_top3_performance import apply

NOW=datetime(2026,10,22,17,tzinfo=timezone(timedelta(hours=9)))
REC={'event_id':'SPORTS-SOCCER-401884766','provider_event_id':'401884766','provider':'ESPN_PUBLIC','sport':'SOCCER','date':'2026-10-17','event_date':'2026-10-17','home':'Werder Bremen','away':'SC Paderborn 07','pick_key':'HOME','locked_odds':1.7692,'start_timestamp':1792243800,'source_url':'https://site.api.espn.com/apis/site/v2/sports/soccer/ger.1/scoreboard?dates=20261017'}
PAYLOAD={'header':{'id':'401884766','competitions':[{'id':'401884766','date':'2026-10-17T13:30Z','status':{'type':{'completed':True,'state':'post','name':'STATUS_FULL_TIME'}},'competitors':[{'homeAway':'home','team':{'id':'137','displayName':'Werder Bremen'},'score':'2'},{'homeAway':'away','team':{'id':'3307','displayName':'SC Paderborn 07'},'score':'2'}]}]}}

class RecoveryTests(unittest.TestCase):
    def test_aged_draw_is_loss_and_locked_odds_unchanged(self):
        rec=copy.deepcopy(REC); records={rec['event_id']:rec}
        snap=recover_pending(records,NOW,lambda url:copy.deepcopy(PAYLOAD))
        result=apply({'date':'2026-10-22','events':[]},{'records':records},NOW,[(snap['date'],snap)])
        row=result['records'][rec['event_id']]
        self.assertFalse(row['evaluation']['hit'])
        self.assertEqual(row['evaluation']['source'],'ESPN_EVENT_SUMMARY_RECHECK')
        self.assertEqual(row['virtual_bet']['profit_krw'],-100000)
        self.assertEqual(row['locked_odds'],1.7692)

    def test_identity_mismatch_rejected(self):
        for kind in ('id','date','team','score'):
            data=copy.deepcopy(PAYLOAD); c=data['header']['competitions'][0]
            if kind=='id':data['header']['id']='999'
            if kind=='date':c['date']='2026-10-18T13:30Z'
            if kind=='team':c['competitors'][0]['team']['displayName']='Other'
            if kind=='score':c['competitors'][0]['score']='NaN'
            with self.subTest(kind=kind),self.assertRaises(ValueError):final_event(REC,data)

    def test_ssrf_and_bad_ids_rejected(self):
        for url in ('http://site.api.espn.com/apis/site/v2/sports/soccer/ger.1/scoreboard','https://evil.example/apis/site/v2/sports/soccer/ger.1/scoreboard','https://site.api.espn.com@evil.example/apis/site/v2/sports/soccer/ger.1/scoreboard','https://site.api.espn.com/apis/site/v2/sports/soccer/../scoreboard'):
            self.assertIsNone(summary_url(dict(REC,source_url=url)))
        self.assertIsNone(summary_url(dict(REC,provider_event_id='1&redirect=evil')))

    def test_network_failure_stays_pending_and_cooldown_applies(self):
        records={REC['event_id']:copy.deepcopy(REC)}
        def fail(url):raise TimeoutError('secret detail never persisted')
        self.assertEqual(recover_pending(records,NOW,fail)['events'],[])
        self.assertNotIn('evaluation',records[REC['event_id']])
        def forbidden(url):self.fail('must respect cooldown')
        recover_pending(records,NOW,forbidden)
        self.assertNotIn('secret',str(records))

    def test_non_final_never_settles(self):
        data=copy.deepcopy(PAYLOAD);data['header']['competitions'][0]['status']['type']['completed']=False
        self.assertIsNone(final_event(REC,data))

    def test_no_odds_is_excluded_even_after_recovery(self):
        rec=copy.deepcopy(REC);rec.pop('locked_odds')
        records={rec['event_id']:rec};snap=recover_pending(records,NOW,lambda url:PAYLOAD)
        result=apply({'date':'2026-10-22','events':[]},{'records':records},NOW,[(snap['date'],snap)])
        self.assertEqual(result['records'][rec['event_id']]['virtual_bet']['state'],'EXCLUDED_NO_LOCKED_ODDS')

if __name__=='__main__':unittest.main()
