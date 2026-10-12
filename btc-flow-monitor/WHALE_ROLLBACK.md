# BTC Whale Tracker — Recovery

Recovery point before whale-tracker integration:

- Branch: `backup/btc-flow-pre-whale-20261012`
- Commit: `f84b0f2ef69c9ac940fada91255d6c299f106149`

## Safe rollback — preserve collected records

1. Restore `btc-flow-monitor/` code from the backup branch, or remove only the whale module files added after the recovery point.
2. In Supabase, disable the whale feature instead of deleting its records:

```sql
update public.whale_settings set enabled=false where id=1;
update public.whale_paper_settings set enabled=false where id=1;
select cron.unschedule(jobid)
from cron.job
where jobname in (
  'btc-hl-whale-cycle-every-minute',
  'btc-hl-whale-stats-hourly',
  'btc-hl-whale-state-every-5min'
);
```

This stops new whale collection/paper processing while retaining `whale_targets`, target history, fills, paper events and paper positions for audit.

## Re-enable

Re-enable only after recreating the three cron jobs from the current migration definitions and setting `whale_settings.enabled=true`, `whale_paper_settings.enabled=true`.

Do not drop the `whale_*` tables for routine rollback; they contain audit/history records.