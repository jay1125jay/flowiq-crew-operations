import unittest
from copy import deepcopy
from datetime import datetime,timedelta
from racing_paper import update,KST
class PaperTest(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,10,25,10,tzinfo=KST)
  self.e={'id':'test','sport':'HORSE','event_date':'2026-10-25','start_time':'11:00','status':'SCHEDULED','outcomes':[{'key':'N1','name':'A','model_p':.6},{'key':'N2','name':'B','model_p':.4}]}
 def snap(self,e):return {'generated_at':self.now.isoformat(),'events':[e]}
 def final(self,odds=2):
  e=deepcopy(self.e);e.update(status='FINAL',result={'official':True,'status':'CONFIRMED','source':'KRA_SCORETABLE_OFFICIAL','top3':[{'rank':1,'number':1}],'markets':[{'market':'단승식','winner':'1','odds':odds}]});return e
 def test_lock_and_settle(self):
  d=update({},self.snap(self.e),[],self.now);self.e['outcomes'][1]['model_p']=.9
  update(d,self.snap(self.e),[],self.now);self.assertEqual(d['records']['test']['pick_key'],'N1')
  update(d,self.snap(self.final()),[],self.now);self.assertEqual(d['summary']['overall']['net_krw'],100000)
  update(d,self.snap(self.final()),[],self.now);self.assertEqual(d['summary']['overall']['settled'],1)
 def test_no_retrospective(self):
  self.assertFalse(update({},self.snap(self.final()),[],self.now)['records'])
  self.assertFalse(update({},self.snap(self.e),[],self.now+timedelta(hours=2))['records'])
 def test_missing_odds(self):
  d=update({},self.snap(self.e),[],self.now);update(d,self.snap(self.final(None)),[],self.now)
  s=d['summary']['overall'];self.assertEqual(s['hits'],1);self.assertIsNone(s['roi']);self.assertEqual(s['stake_krw'],0)
 def test_loss_and_history(self):
  self.e['outcomes'][0]['model_p']=.4;self.e['outcomes'][1]['model_p']=.6
  d=update({},self.snap(self.e),[],self.now);update(d,{'events':[]},[self.snap(self.final())],self.now)
  self.assertEqual(d['summary']['overall']['net_krw'],-100000)
 def test_unknown_time(self):
  self.e['start_time']='';self.assertFalse(update({},self.snap(self.e),[],self.now)['records'])
 def test_four_sports(self):
  sources={'CYCLE':'KCYCLE_RESULT_OFFICIAL','BOAT':'KBOAT_RESULT_OFFICIAL','BULL':'CPC_RESULT_OFFICIAL'}
  for sport,source in sources.items():
   e=deepcopy(self.e);e['sport']=sport
   if sport=='BULL':e['outcomes']=[{'key':'RED','model_p':.6},{'key':'BLUE','model_p':.3},{'key':'DRAW','model_p':.1}]
   d=update({},self.snap(e),[],self.now)
   e['status']='FINAL';e['result']={'official':True,'status':'CONFIRMED','source':source,'top3':[{'rank':1,'number':1}],'winner':{'key':'RED'},'markets':[{'market':'단승식','winner':'홍' if sport=='BULL' else '1','odds':2.5}]}
   update(d,self.snap(e),[],self.now);self.assertEqual(d['summary']['overall']['net_krw'],150000)
 def test_unofficial(self):
  d=update({},self.snap(self.e),[],self.now);e=self.final();e['result']['official']=False
  update(d,self.snap(e),[],self.now);self.assertEqual(d['summary']['overall']['pending'],1)
if __name__=='__main__':unittest.main()
