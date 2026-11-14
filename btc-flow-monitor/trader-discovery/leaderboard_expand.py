#!/usr/bin/env python3
"""Build a diversified public Hyperliquid trader candidate pool. PAPER research only."""
import datetime as dt
import json, pathlib, re, urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=pathlib.Path(__file__).resolve().parent/'candidate-pool.json'
WATCH=ROOT/'data'/'whale-watchlist.json'
URL='https://stats-data.hyperliquid.xyz/Mainnet/leaderboard'
ADDRESS=re.compile(r'^0x[a-fA-F0-9]{40}$')
DIVERSIFIED_LIMIT=48
PROFIT_LEADERS=128
POOL_LIMIT=DIVERSIFIED_LIMIT+PROFIT_LEADERS
PER_BUCKET=16
MIN_ACCOUNT_VALUE=10_000.0
WINDOWS=('day','week','month','allTime')

def num(v,default=0.0):
    try:return float(v)
    except (TypeError,ValueError):return default

def parse_rows(payload):
    out=[]
    for row in payload.get('leaderboardRows',[]):
        addr=str(row.get('ethAddress') or '').lower()
        if not ADDRESS.fullmatch(addr):continue
        perf={}
        for item in row.get('windowPerformances') or []:
            if isinstance(item,list) and len(item)>=2 and isinstance(item[1],dict):perf[str(item[0])]=item[1]
        out.append({'address':addr,'display_name':row.get('displayName'),'account_value_usd':num(row.get('accountValue')),
                    'windows':{w:{'pnl_usd':num(perf.get(w,{}).get('pnl')),'roi':num(perf.get(w,{}).get('roi')),'volume_usd':num(perf.get(w,{}).get('vlm'))} for w in WINDOWS}})
    return out

def select(rows,watch):
    eligible=[r for r in rows if r['account_value_usd']>=MIN_ACCOUNT_VALUE and r['windows']['allTime']['pnl_usd']>0]
    chosen={}
    for a in watch:
        match=next((r for r in rows if r['address']==a),None)
        chosen[a]=dict(match or {'address':a,'display_name':None,'account_value_usd':0,'windows':{}})
        chosen[a]['seed']='existing_watchlist'
    # Draw fairly from every time window. The previous greedy selection filled
    # the whole pool with daily leaders before ever reaching monthly/all-time.
    buckets=[]
    for w in WINDOWS:
        profitable=[r for r in eligible if r['windows'][w]['pnl_usd']>0]
        for metric in ('pnl_usd','roi'):
            ranked=sorted(profitable,key=lambda r:r['windows'][w][metric],reverse=True)[:PER_BUCKET]
            buckets.append((w,metric,ranked))
    for rank in range(PER_BUCKET):
        for w,metric,ranked in buckets:
            if len(chosen)>=DIVERSIFIED_LIMIT:break
            if rank>=len(ranked):continue
            row=ranked[rank]
            if row['address'] not in chosen:
                picked=dict(row);picked['seed']=f'{w}_{metric}'
                chosen[row['address']]=picked
        if len(chosen)>=DIVERSIFIED_LIMIT:break
    # Ensure a full pool even when the same trader ranks in many buckets.
    for row in sorted(eligible,key=lambda r:(r['windows']['allTime']['pnl_usd'],r['windows']['month']['volume_usd']),reverse=True):
        if len(chosen)>=DIVERSIFIED_LIMIT:break
        if row['address'] not in chosen:
            picked=dict(row);picked['seed']='allTime_diversity_backfill'
            chosen[row['address']]=picked
    for row in sorted(eligible, key=lambda r: (-r['windows']['allTime']['pnl_usd'], r['address']))[:PROFIT_LEADERS]:
        if row['address'] not in chosen:
            chosen[row['address']] = dict(row, seed='allTime_profit_leader')
    return list(chosen.values())[:POOL_LIMIT]

def main():
    req=urllib.request.Request(URL,headers={'User-Agent':'BTC-Flow-Paper-Research/3.0'})
    with urllib.request.urlopen(req,timeout=40) as res:payload=json.load(res)
    rows=parse_rows(payload)
    watch=[]
    if WATCH.exists():watch=[str(x).lower() for x in json.loads(WATCH.read_text()).get('addresses',[]) if ADDRESS.fullmatch(str(x))]
    candidates=select(rows,watch)
    out={'schema_version':1,'paper_only':True,'real_trading_enabled':False,'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),
         'source':'Hyperliquid public Mainnet leaderboard','source_rows':len(rows),'pool_limit':POOL_LIMIT,'candidate_count':len(candidates),
         'selection':{'min_account_value_usd':MIN_ACCOUNT_VALUE,'requires_positive_all_time_pnl':True,'windows':list(WINDOWS),'per_bucket':PER_BUCKET},
         'candidates':candidates}
    OUT.write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'source_rows':len(rows),'candidate_count':len(candidates)},ensure_ascii=False))
    if len(candidates)<len(watch):raise RuntimeError('candidate pool lost watchlist seeds')

if __name__=='__main__':main()
