import argparse
import json
import time
from datetime import datetime, timezone, timedelta

import historical_backfill as hb
import historical_backfill_hardening as hardening
import historical_cycle_result_fallback as cycle_result_fallback
import historical_retry_repair as retry_repair

hardening.install(hb)
cycle_result_fallback.install(hb)
retry_repair.install(hb)

KST=timezone(timedelta(hours=9))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--horse-slice',type=int,default=2500)
    ap.add_argument('--ksports-slice',type=int,default=2500)
    ap.add_argument('--bull-slice',type=int,default=4500)
    ap.add_argument('--max-seconds',type=int,default=1500)
    args=ap.parse_args()

    state=hb.load_state()
    today=datetime.now(KST).date().isoformat()
    start=time.monotonic()
    total=max(30,args.max_seconds)
    budget=hb.Budget(state,today,{
        'horse':max(0,args.horse_slice),
        'ksports':max(0,args.ksports_slice),
        'bull':max(0,args.bull_slice),
    },start+total)
    seen={s:hb.existing_ids(s) for s in ('horse','cycle','boat','bull')}
    stats={
        'horse_records':0,'horse_dates':0,
        'horse_retry_attempted':0,'horse_retry_recovered':0,
        'cycle_records':0,'cycle_dates':0,
        'boat_records':0,'boat_dates':0,
        'bull_records':0,'bull_cards':0,
        'errors':[],
    }
    before=dict(budget.ledger)

    # Catch-up priority: KCYCLE is far behind the other sports. Until at
    # least 100 clean cycle races exist, give it enough wall-clock time to
    # cross non-meeting weekends and reach the next real meeting.
    cycle_backlog = len(seen['cycle']) < 100
    if cycle_backlog:
        horse_end=start+total*0.20
        cycle_end=start+total*0.65
        boat_end=start+total*0.78
    else:
        horse_end=start+total*0.35
        cycle_end=start+total*0.525
        boat_end=start+total*0.70
    bull_end=start+total

    budget.deadline=horse_end
    if budget.available('horse')>0:
        hb.backfill_horse(state,budget,seen['horse'],stats)

    shared_remaining=budget.available('ksports')
    cycle_calls=(shared_remaining+1)//2
    boat_calls=shared_remaining-cycle_calls

    budget.deadline=cycle_end
    if cycle_calls>=1:
        hb.backfill_cycle(state,budget,seen['cycle'],stats,cycle_calls)

    budget.deadline=boat_end
    if boat_calls>=2:
        hb.backfill_boat(state,budget,seen['boat'],stats,boat_calls)

    # Reallocate unused shared KSPORTS quota instead of leaving it stranded.
    # Alternate small chunks so KCYCLE and KBOAT both get repeated chances.
    budget.deadline=boat_end
    while budget.available('ksports') >= 2 and budget.time_left():
        before_shared = int(budget.ledger.get('ksports', 0))
        remaining = budget.available('ksports')
        chunk = min(120, remaining)
        cycle_chunk = max(1, chunk // 2)
        boat_chunk = max(1, chunk - cycle_chunk)
        if not state['checkpoints']['cycle'].get('complete') and cycle_chunk >= 1:
            hb.backfill_cycle(state,budget,seen['cycle'],stats,cycle_chunk)
        if budget.available('ksports') >= 2 and budget.time_left() and not state['checkpoints']['boat'].get('complete') and boat_chunk >= 2:
            hb.backfill_boat(state,budget,seen['boat'],stats,min(boat_chunk,budget.available('ksports')))
        if int(budget.ledger.get('ksports', 0)) == before_shared:
            break

    budget.deadline=bull_end
    if budget.available('bull')>0:
        hb.backfill_bull(state,budget,seen['bull'],stats)

    hb.save_state(state)
    report={
        'generated_at':datetime.now(KST).isoformat(timespec='seconds'),
        'mode':'OFFICIAL_READONLY_HISTORICAL_BACKFILL_FAIR_RUNTIME_HARDENED',
        'caps':hb.CAPS,
        'usage_today':budget.ledger,
        'usage_before_run':before,
        'checkpoints':state['checkpoints'],
        'new':stats,
        'records_total':{s:len(seen[s]) for s in seen},
        'retry_metrics':state.get('retry_metrics',{}),
        'quota_policy':'daily hard caps; use remaining quota opportunistically; KCYCLE/KBOAT start 50/50 then reallocate unused shared quota',
        'runtime_policy':({'horse':0.20,'cycle_until':0.65,'boat_until':0.78,'bull_until':1.0,'mode':'CYCLE_CATCHUP_UNTIL_100'} if cycle_backlog else {'horse':0.35,'cycle_until':0.525,'boat_until':0.70,'bull_until':1.0,'mode':'BALANCED'}),
        'runtime_seconds':total,
        'hardening':{
            'horse':'STRICT_RENDERED_RACE_AND_ROW_QUALITY_BEFORE_PERSIST_PLUS_RETRY_QUEUE_REPLAY',
            'cycle':'DATE_SAFE_RESULT_URL_FALLBACK_AND_NON_MEETING_ADVANCE',
        },
    }
    hb.REPORT_FILE.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'HISTORICAL_BACKFILL':'PASS',**report},ensure_ascii=False))

if __name__=='__main__':main()
