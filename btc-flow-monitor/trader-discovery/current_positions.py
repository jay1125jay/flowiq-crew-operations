#!/usr/bin/env python3
"""Observe current BTC direction for every classified trader. Public Hyperliquid data; PAPER only."""
import datetime as dt,json,pathlib,time,urllib.request,urllib.error
ROOT=pathlib.Path(__file__).resolve().parents[1]
COHORT=ROOT/'trader-discovery/latest.json'; OUT=ROOT/'trader-discovery/current-positions.json'
API='https://api.hyperliquid.xyz/info'
def api(payload):
 req=urllib.request.Request(API,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','User-Agent':'BTC-Flow-Paper-Research/2.0'},method='POST')
 for attempt in range(3):
  try:
   with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
  except (urllib.error.URLError, TimeoutError):
   if attempt==2:raise
   time.sleep(2**attempt)
def btc(state):
 for x in state.get('assetPositions',[]):
  p=x.get('position',{})
  if p.get('coin')=='BTC':
   s=float(p.get('szi') or 0);return 'LONG' if s>0 else 'SHORT' if s<0 else 'FLAT'
 return 'FLAT'
def main():
 c=json.loads(COHORT.read_text()); assert c.get('paper_only') and not c.get('real_trading_enabled')
 rows=c.get('wallets',[]); current_addresses={w.get('address') for w in rows if w.get('address')}; signals={}; errors=[]
 previous_catalog=set()
 if OUT.exists():
  try:
   previous=json.loads(OUT.read_text())
   previous_catalog=set(previous.get('catalog_addresses') or previous.get('wallets',{}).keys())
  except Exception:previous_catalog=set()
 retired=previous_catalog-current_addresses
 for i,w in enumerate(rows):
  a=w.get('address')
  if not a:continue
  try:signals[a]=btc(api({'type':'clearinghouseState','user':a}))
  except Exception as e:errors.append({'address':a,'error':type(e).__name__})
  if i and i%10==0:time.sleep(.35)
 # A trader removed by the fresh/skill cohort filter is emitted as FLAT for one cycle.
 # This lets PAPER followers close stale/unqualified positions instead of holding them forever.
 for a in retired:signals[a]='FLAT'
 price=float(api({'type':'allMids'})['BTC'])
 if not 1000<price<1000000:raise ValueError('invalid BTC mid')
 out={'schema_version':2,'paper_only':True,'real_trading_enabled':False,'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'btc_mid_usd':price,'catalog_wallet_count':len(rows),'catalog_addresses':sorted(current_addresses),'retired_wallet_count':len(retired),'observed_wallet_count':len(current_addresses)-len(errors),'errors':errors,'wallets':signals}
 OUT.write_text(json.dumps(out,indent=2)+'\n');print('FULL POSITION OBSERVATION PASS',len(current_addresses)-len(errors),'/',len(rows),'retired',len(retired),'errors',len(errors))
if __name__=='__main__':main()
