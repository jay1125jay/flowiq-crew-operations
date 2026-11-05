#!/usr/bin/env python3
import json
import datetime as dt
from pathlib import Path
import category_top6_policy
from replay_snapshot_merge import _coverage

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'trader-discovery'/'cloud-replay-log.json'
MAX_EVENTS=2016

def main():
    cohort=json.loads((ROOT/'trader-discovery'/'latest.json').read_text(encoding='utf-8'))
    pos=json.loads((ROOT/'trader-discovery'/'current-positions.json').read_text(encoding='utf-8'))
    if not cohort.get('paper_only') or cohort.get('real_trading_enabled'): raise ValueError('PAPER only')
    if not pos.get('paper_only') or pos.get('real_trading_enabled'): raise ValueError('PAPER only')
    ranked=category_top6_policy.apply_top6_policy(cohort)
    source_id=str(pos.get('generated_at') or '')
    price=float(pos.get('btc_mid_usd') or 0)
    if not source_id or not 1000<price<1000000: raise ValueError('bad source')
    rows=[]
    for r in ranked.get('wallets',[]):
        flags={k:bool(v) for k,v in (r.get('category_flags') or {}).items() if v}
        if flags and r.get('address'): rows.append({'address':r['address'],'category_flags':flags})
    event={'id':source_id,'at':source_id,'btc_mid_usd':price,'cohort_wallets':rows,'wallets':pos.get('wallets',{})}
    payload={'schema_version':1,'paper_only':True,'real_trading_enabled':False,'events':[]}
    if OUT.exists():
        try:
            old=json.loads(OUT.read_text(encoding='utf-8'))
            if old.get('schema_version')==1: payload=old
        except Exception: pass
    by_id={str(e.get('id')):e for e in payload.get('events',[]) if e.get('id')}
    by_id[source_id]=event
    payload['events']=sorted(by_id.values(),key=lambda e:str(e.get('at') or ''))[-MAX_EVENTS:]
    payload['updated_at']=source_id
    payload['cadence_seconds']=300
    payload['max_events']=MAX_EVENTS
    payload['capture_health']=_coverage(payload['events'],dt.datetime.now(dt.timezone.utc).timestamp())
    OUT.write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
    print('CLOUD REPLAY LOG PASS',len(payload['events']))

if __name__=='__main__': main()
