#!/usr/bin/env python3
"""Replay persisted cloud PAPER events into a stale local PC category ledger."""
import copy
import datetime as dt
import math
import json
import urllib.request

REPLAY_URL='https://raw.githubusercontent.com/jay1125jay/flowiq-crew-operations/main/btc-flow-monitor/trader-discovery/cloud-replay-log.json'
TIMEOUT_SECONDS=15


def _ts(value):
    try:return dt.datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
    except Exception:return 0.0


def fetch_events():
    req=urllib.request.Request(REPLAY_URL,headers={'User-Agent':'BTC-Flow-PC-Paper-Recovery/1.0'})
    with urllib.request.urlopen(req,timeout=TIMEOUT_SECONDS) as res: payload=json.load(res)
    if payload.get('paper_only') is not True or payload.get('real_trading_enabled') is not False:
        raise ValueError('replay log must remain PAPER ONLY')
    return list(payload.get('events') or [])


def recover(state,source_id,category_module,now_iso):
    if not state or not state.get('updated_at'):
        return state,source_id,{'status':'SKIP_NO_LOCAL_STATE','replayed':0}
    local_ts=_ts(state.get('updated_at'))
    now_ts=_ts(now_iso)
    if local_ts<=0 or now_ts<=local_ts:
        return state,source_id,{'status':'SKIP_FRESH','replayed':0}
    try: events=fetch_events()
    except Exception as exc:
        return state,source_id,{'status':'FETCH_FAILED','replayed':0,'error':type(exc).__name__}
    pending=[e for e in events if local_ts<_ts(e.get('at'))<=now_ts]
    pending.sort(key=lambda e:_ts(e.get('at')))
    if not pending:
        return state,source_id,{'status':'NO_CLOUD_EVENTS','replayed':0}
    recovered=copy.deepcopy(state)
    first_at=None;last_at=None;applied_at=[]
    for event in pending:
        at=str(event.get('at') or '')
        price=float(event.get('btc_mid_usd') or 0)
        stamp=_ts(at)
        if not at or not 1000<price<1000000 or stamp<=0:
            continue
        cohort={'paper_only':True,'real_trading_enabled':False,'wallets':copy.deepcopy(event.get('cohort_wallets') or [])}
        wallets=copy.deepcopy(event.get('wallets') or {})
        feed={'paper_only':True,'real_trading_enabled':False,'generated_at':at,'btc_mid_usd':price,
              'wallets':wallets,'observed_wallet_count':len(wallets),'errors':[]}
        recovered=category_module.advance(recovered,cohort,feed,at)
        if first_at is None:first_at=at
        last_at=at
        applied_at.append(stamp)
    if not applied_at:
        return state,source_id,{'status':'INVALID_CLOUD_EVENTS','replayed_events':0}
    expected=max(0,int((now_ts-local_ts)//300))
    missing=max(0,expected-len(applied_at))
    check_points=[local_ts]+applied_at+[now_ts]
    max_gap=round(max(b-a for a,b in zip(check_points,check_points[1:])),1)
    # GitHub scheduled jobs can be delayed or dropped. Never claim full
    # gap recovery when the underlying snapshots were not collected.
    complete=(max_gap<=900 and (expected==0 or len(applied_at)>=max(1,int(expected*0.8))))
    recovered['gap_recovery']={
        'status':'REPLAYED' if complete else 'PARTIAL_REPLAY',
        'mode':'CLOUD_5_MINUTE_PAPER_REPLAY',
        'replayed_events':len(applied_at),
        'expected_5m_events':expected,
        'missing_5m_events_estimate':missing,
        'coverage_pct':round(100*min(1.0,len(applied_at)/max(1,expected)),1),
        'max_gap_seconds':max_gap,
        'from_local_at':state.get('updated_at'),
        'first_replay_at':first_at,'last_replay_at':last_at,
        'completed_at':now_iso,
        'limitation':'Saved cloud snapshots only; skipped 5-minute windows cannot be reconstructed as actual trader positions',
    }

    return recovered,(last_at or source_id),recovered['gap_recovery']
