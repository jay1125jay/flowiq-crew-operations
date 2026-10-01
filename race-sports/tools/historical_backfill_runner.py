import argparse
import json
import time
from datetime import datetime, timezone, timedelta

import historical_backfill as hb
import historical_backfill_hardening as hardening

hardening.install(hb)

KST=timezone(timedelta(hours=9))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--horse-slice',type=int,default=625)
    ap.add_argument('--ksports-slice',type=int,default=625)
    ap.add_argument('--bull-slice',type=int,default=1125)
    ap.add_argument('--max-seconds',type=int,default=1500)
    args=ap.parse_args()

    state=hb.load_state()
    today=datetime.now(KST).date().isoformat()
    start=time.monotonic()
    # Respect the workflow's requested runtime. A small floor only protects
    # against accidental zero/negative values; smoke/retry jobs must not be
    # silently expanded to five minutes.
    total=max(30,args.max_seconds)
    budget=hb.Budget(state,today,{
        'horse':max(0,args.horse_slice),
        'ksports':max(0,args.ksports_slice),
        'bull':max(0,args.bull_slice),
    },start+total)
    seen={s:hb.existing_ids(s) for s in ('horse','cycle','boat','bull')}
    stats={
        'horse_records':0,'horse_dates':0,
        'cycle_records':0,'cycle_dates':0,
        'boat_records':0,'boat_dates':0,
        'bull_records':0,'bull_cards':0,
        'errors':[],
    }
    before=dict(budget.ledger)

    # Hard runtime partitions prevent any single provider from starving others.
    horse_end=start+total*0.40
    cycle_end=start+total*0.55
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
        'quota_policy':'daily hard caps; four KST-day slices; KCYCLE/KBOAT share KSPORTS quota 50/50 unless completed',
        'runtime_policy':{'horse':0.40,'cycle':0.15,'boat':0.15,'bull':0.30},
        'runtime_seconds':total,
        'hardening':{
            'horse':'STRICT_RENDERED_RACE_AND_ROW_QUALITY_BEFORE_PERSIST',
            'cycle':'404_NON_MEETING_ADVANCES_CHECKPOINT_TRANSIENT_ERRORS_RETRY',
        },
    }
    hb.REPORT_FILE.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'HISTORICAL_BACKFILL':'PASS',**report},ensure_ascii=False))

if __name__=='__main__':main()
