#!/usr/bin/env python3
"""Observe current BTC direction for every classified trader. Public Hyperliquid data; PAPER only."""
import datetime as dt,json,pathlib,time,urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
COHORT=ROOT/'trader-discovery/latest.json'; OUT=ROOT/'trader-discovery/current-positions.json'
API='https://api.hyperliquid.xyz/info'
def api(payload):
 req=urllib.request.Request(API,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','User-Agent':'BTC-Flow-Paper-Research/2.0'},method='POST')
 with urllib.request.urlopen(req,timeout=25) as r:return json.load(r)
def btc(state):
 for x in state.get('assetPositions',[]):
  p=x.get('position',{})
  if p.get('coin')=='BTC':
   s=float(p.get('szi') or 0);return 'LONG' if s>0 else 'SHORT' if s<0 else 'FLAT'
 return 'FLAT'
def main():
 c=json.loads(COHORT.read_text()); assert c.get('paper_only') and not c.get('real_trading_enabled')
 rows=c.get('wallets',[]); signals={}; errors=[]
 for i,w in enumerate(rows):
  a=w.get('address')
  if not a:continue
  try:signals[a]=btc(api({'type':'clearinghouseState','user':a}))
  except Exception as e:errors.append({'address':a,'error':type(e).__name__})
  if i and i%10==0:time.sleep(.35)
 price=float(api({'type':'allMids'})['BTC'])
 if not 1000<price<1000000:raise ValueError('invalid BTC mid')
 out={'schema_version':1,'paper_only':True,'real_trading_enabled':False,'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'btc_mid_usd':price,'catalog_wallet_count':len(rows),'observed_wallet_count':len(signals),'errors':errors,'wallets':signals}
 OUT.write_text(json.dumps(out,indent=2)+'\n');print('FULL POSITION OBSERVATION PASS',len(signals),'/',len(rows),'errors',len(errors))
if __name__=='__main__':main()
