#!/usr/bin/env python3
"""Public Hyperliquid BTC trader cohort research. PAPER ONLY; never places orders."""
import datetime as dt
import json, math, pathlib, statistics, time, urllib.error, urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[1]
RANK=ROOT/'data'/'whale-ranking.json'
OUT=pathlib.Path(__file__).resolve().parent/'latest.json'
API='https://api.hyperliquid.xyz/info'
EPS=1e-12
CATALOG_TTL_SECONDS=6*60*60
FORWARD_MIN_DAYS=7
FORWARD_MIN_CLOSES=20
CLASSIFIER_VERSION=4


def query(payload):
    req=urllib.request.Request(API,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','User-Agent':'BTC-Flow-Trader-Research/2.0'},method='POST')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req,timeout=20) as res:return json.load(res)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt==2:raise
        except (urllib.error.URLError,TimeoutError):
            if attempt==2:raise
        time.sleep(1.5*(attempt+1))

def signed_after(fill):
    start=float(fill.get('startPosition') or 0); sz=abs(float(fill.get('sz') or 0)); side=fill.get('side')
    return start+(sz if side=='B' else -sz if side=='A' else 0)

def holding_episodes(fills):
    episodes=[]; opened_at=None; open_side=None
    for f in sorted((x for x in fills if x.get('coin')=='BTC'),key=lambda x:(int(x.get('time') or 0),int(x.get('tid') or 0))):
        t=int(f.get('time') or 0); start=float(f.get('startPosition') or 0); after=signed_after(f); ss=1 if start>EPS else -1 if start<-EPS else 0; aa=1 if after>EPS else -1 if after<-EPS else 0
        if ss==0 and aa!=0:opened_at=t; open_side='LONG' if aa>0 else 'SHORT'
        elif ss!=0 and aa==0:
            if opened_at is not None and t>=opened_at:episodes.append({'side':open_side or ('LONG' if ss>0 else 'SHORT'),'opened_at':opened_at,'closed_at':t,'holding_seconds':(t-opened_at)/1000})
            opened_at=None; open_side=None
        elif ss!=0 and aa!=0 and ss!=aa:
            if opened_at is not None and t>=opened_at:episodes.append({'side':open_side or ('LONG' if ss>0 else 'SHORT'),'opened_at':opened_at,'closed_at':t,'holding_seconds':(t-opened_at)/1000})
            opened_at=t; open_side='LONG' if aa>0 else 'SHORT'
    return episodes

def pct(values,p):
    if not values:return None
    v=sorted(values); i=(len(v)-1)*p; lo=math.floor(i); hi=math.ceil(i); return v[lo] if lo==hi else v[lo]*(hi-i)+v[hi]*(i-lo)

def classify(rank,fills,now):
    btc=[f for f in fills if f.get('coin')=='BTC']; eps=holding_episodes(btc); holds=[e['holding_seconds'] for e in eps]; med=statistics.median(holds) if holds else None; short_share=sum(x<=3600 for x in holds)/len(holds) if holds else 0; long_share=sum(x>=3600 for x in holds)/len(holds) if holds else 0
    closes=int(rank.get('history_sample_closes') or 0); win=rank.get('history_sample_win_rate_pct'); pnl=float(rank.get('history_sample_net_pnl_usd') or 0); notional=float(rank.get('history_avg_fill_notional_usd') or 0); hist_pf=float(rank.get('history_profit_factor') or 0)
    fwd=float(rank.get('forward_net_pnl_usd') or 0); dd=float(rank.get('forward_drawdown_usd') or 0); pf=float(rank.get('forward_profit_factor') or 0); conc=float(rank.get('forward_largest_win_share_pct') or 100); forward_days=float(rank.get('forward_observed_days') or 0); forward_closes=int(rank.get('forward_closes') or 0)
    stress_raw=rank.get('forward_stress_net_pnl_usd'); forward_stress=float(fwd if stress_raw is None else stress_raw)
    forward_mature=forward_days>=FORWARD_MIN_DAYS and forward_closes>=FORWARD_MIN_CLOSES
    upstream_eligible=rank.get('eligible_for_paper_observation')
    if not forward_mature:
        forward_gate=True
    elif upstream_eligible is None:
        forward_gate=forward_stress>0 and pf>=1.05 and conc<=65
    else:
        forward_gate=bool(upstream_eligible) and forward_stress>0
    # Hyperliquid userFills returns a capped recent history across *all* coins.
    # Recent BTC closes can be few even when our monotonic BTC-only forward
    # cursor has verified hundreds of closes over weeks. Use that independent
    # evidence only when VERIFIED, forward-profitable, and recent BTC sample is positive.
    verified_forward=bool(rank.get('verified_whale')) and forward_mature and forward_gate and pf>=1.05 and conc<=65 and 3<=closes<20 and pnl>0 and rank.get('forward_win_rate_pct') is not None
    history_gate=bool(rank.get('paper_candidate')) or (closes>=20 and win is not None and float(win)>=45 and pnl>0 and hist_pf>=1.05) or verified_forward
    skill_ok=history_gate and forward_gate
    category_closes=max(closes,forward_closes) if verified_forward else closes
    category_win=float(rank.get('forward_win_rate_pct') or 0) if verified_forward else (float(win) if win is not None else 0)
    category_profit=forward_stress if verified_forward else pnl
    cats={'WHALE':skill_ok and notional>=20000 and category_closes>=20,
          'HIGH_WIN_RATE':skill_ok and category_closes>=50 and category_win>=65,
          'HIGH_PROFIT':skill_ok and category_closes>=50 and category_profit>=10000,
          'CONSISTENT':skill_ok and forward_closes>=20 and fwd>0 and pf>=1.5 and conc<=20 and dd<=max(500,abs(fwd)*0.25),
          'SCALPER':skill_ok and len(holds)>=10 and med is not None and med<=900 and short_share>=.60,
          'SWING':skill_ok and len(holds)>=5 and med is not None and med>=14400 and long_share>=.60}
    return {'classifier_version':CLASSIFIER_VERSION,'address':rank['address'],'last_scanned_at':now,'categories':[k for k,v in cats.items() if v],'category_flags':cats,'skill_gate_passed':skill_ok,'history_gate_passed':history_gate,'forward_gate_passed':forward_gate,'forward_mature':forward_mature,'verified_forward_evidence_used':verified_forward,'category_stat_source':'VERIFIED_BTC_FORWARD' if verified_forward else 'RECENT_BTC_HISTORY','history':{'fills_returned':len(btc),'history_capped':len(fills)>=2000,'closes':closes,'win_rate_pct':win,'net_pnl_usd':pnl,'profit_factor':hist_pf,'avg_fill_notional_usd':notional},'holding':{'complete_episodes':len(holds),'median_seconds':round(med,1) if med is not None else None,'p90_seconds':round(pct(holds,.9),1) if holds else None,'within_1h_share':round(short_share,3) if holds else None,'at_least_1h_share':round(long_share,3) if holds else None},'forward':{'days':forward_days,'closes':forward_closes,'win_rate_pct':rank.get('forward_win_rate_pct'),'net_pnl_usd':fwd,'stress_net_pnl_usd':forward_stress,'drawdown_usd':dd,'eligible_for_paper_observation':upstream_eligible},'verified':bool(rank.get('verified_whale',False))}

def _fresh(row,now_dt):
    if int(row.get('classifier_version') or 0)!=CLASSIFIER_VERSION:return False
    try:
        stamp=dt.datetime.fromisoformat(str(row.get('last_scanned_at') or '').replace('Z','+00:00'))
        return 0 <= (now_dt-stamp).total_seconds() <= CATALOG_TTL_SECONDS
    except Exception:return False

def main():
    data=json.loads(RANK.read_text(encoding='utf-8')); now_dt=dt.datetime.now(dt.timezone.utc); now=now_dt.isoformat(); old={}
    if OUT.exists():
        try:old={x['address']:x for x in json.loads(OUT.read_text(encoding='utf-8')).get('wallets',[]) if x.get('address') and _fresh(x,now_dt)}
        except Exception:old={}
    errors=[]; scanned=[]
    for r in data.get('ranked_wallets',[]):
        try:
            fills=query({'type':'userFills','user':r['address'],'aggregateByTime':False}); row=classify(r,fills,now); old[row['address']]=row; scanned.append(row['address'])
        except Exception as e:errors.append({'address':r.get('address'),'error':type(e).__name__})
        time.sleep(.12)
    rows=sorted((x for x in old.values() if _fresh(x,now_dt)),key=lambda x:x.get('last_scanned_at',''),reverse=True); names=('WHALE','HIGH_WIN_RATE','HIGH_PROFIT','CONSISTENT','SCALPER','SWING'); counts={n:sum(bool(x.get('category_flags',{}).get(n)) for x in rows) for n in names}
    out={'schema_version':4,'classifier_version':CLASSIFIER_VERSION,'paper_only':True,'real_trading_enabled':False,'generated_at':now,'source_ranking_updated_at':data.get('updated_at'),'catalog_ttl_seconds':CATALOG_TTL_SECONDS,'catalog_wallet_count':len(rows),'scanned_this_run':len(scanned),'scanned_addresses':scanned,'errors':errors,'candidate_counts':counts,'candidate_diagnostics':{'catalog_wallets':len(rows),'with_btc_closes':sum(x['history']['closes']>0 for x in rows),'history_gate_passed':sum(bool(x['history_gate_passed']) for x in rows),'forward_gate_passed':sum(bool(x['forward_gate_passed']) for x in rows),'qualified_any_category':sum(any(x['category_flags'].values()) for x in rows),'no_btc_closes':sum(x['history']['closes']==0 for x in rows),'nonprofitable_btc_history':sum(x['history']['closes']>0 and x['history']['net_pnl_usd']<=0 for x in rows)},'verification_note':'PAPER research only. Historical candidates may enter while forward evidence is immature; after 7 days and 20 forward closes, a trader must remain eligible under forward verification with positive stress PnL. Cached rows from older classifier versions are invalidated immediately; current rows expire after 6 hours. Hyperliquid userFills is capped at 2000 recent fills.','wallets':rows}
    OUT.write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n',encoding='utf-8'); print(json.dumps({'catalog_wallets':len(rows),'scanned':len(scanned),'errors':len(errors),'candidate_counts':counts},ensure_ascii=False))
    if errors:raise RuntimeError('one or more wallet fetches failed')

if __name__=='__main__':main()
