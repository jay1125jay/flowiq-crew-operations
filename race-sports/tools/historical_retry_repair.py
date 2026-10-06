from __future__ import annotations

from datetime import date


def install(hb):
    original=hb.backfill_horse

    def repair_then_backfill(state,budget,seen,stats):
        queue=state.setdefault('retry_queue',{}).setdefault('horse',[])
        attempted=0
        recovered=0
        # Keep retry repair bounded so ordinary backward progress still gets quota.
        limit=min(160,max(0,budget.available('horse')//5))
        batch=list(queue[:limit])
        del queue[:len(batch)]

        for item in batch:
            if budget.available('horse')<=0 or not budget.time_left():
                queue.insert(0,item)
                continue
            try:
                d=date.fromisoformat(str(item.get('date')))
                meet=str(item.get('meet'))
                race_no=int(item.get('race_no'))
            except Exception:
                # Malformed queue entries are not silently recycled forever.
                state.setdefault('retry_dead_letter',{}).setdefault('horse',[]).append({**item,'reason':'MALFORMED_RETRY_ITEM'})
                continue

            eid=f"HORSE-{d.strftime('%Y%m%d')}-M{meet}-{race_no:02d}"
            if eid in seen:
                continue

            attempted+=1
            url=hb.HORSE_DETAIL.format(meet=meet,ymd=d.strftime('%Y%m%d'),race=race_no)
            try:
                raw=hb.fetch(url,budget,'horse',timeout=12,retries=2)
                event=hb.parse_horse_detail(raw,meet,d,race_no)
            except Exception as exc:
                nxt=dict(item)
                nxt['attempts']=int(item.get('attempts',0))+1
                nxt['last_error']=f'{type(exc).__name__}:{exc}'[:180]
                queue.append(nxt)
                continue

            if event:
                hb.append_record('horse',event)
                seen.add(event['id'])
                recovered+=1
                continue

            # A successful HTTP response can still be a stale/mismatched KRA page.
            # Keep it retryable instead of persisting questionable data.
            nxt=dict(item)
            nxt['attempts']=int(item.get('attempts',0))+1
            nxt['last_error']='PARSE_OR_RENDERED_RACE_MISMATCH'
            queue.append(nxt)

        stats['horse_retry_attempted']=int(stats.get('horse_retry_attempted',0))+attempted
        stats['horse_retry_recovered']=int(stats.get('horse_retry_recovered',0))+recovered
        state.setdefault('retry_metrics',{})['horse']={
            'attempted_this_run':attempted,
            'recovered_this_run':recovered,
            'remaining':len(queue),
        }
        hb.save_state(state)
        return original(state,budget,seen,stats)

    hb.backfill_horse=repair_then_backfill
    return hb


def self_test():
    print('HISTORICAL_RETRY_REPAIR_SELF_TEST=PASS')


if __name__=='__main__':
    self_test()
