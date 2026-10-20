# BTC FLOW external clock (prepared, not activated)

Runs the existing BTC PAPER workflow through GitHub workflow_dispatch every five minutes.
It does not trade, hold funds, modify strategy state, or write repository contents.
GitHub concurrency remains the single writer guard. An active workflow is skipped;
an active run older than 20 minutes fails visibly rather than triggering duplicates.
A POST timeout is not retried. A later clock tick checks run history first.
Workflow dispatch acceptance is not workflow success and does not guarantee exact cadence.

## Concrete deployment configuration

Create a dedicated BTC FLOW service; do not reuse unrelated phoenix-trading services.
Repository: jay1125jay/flowiq-crew-operations, branch main.
Root directory: /btc-flow-monitor/external-clock
Builder: Dockerfile in that root.
Start command: python scheduler.py
Cron schedule: */5 * * * * (UTC)
Restart policy: NEVER
Replicas: 1
No public domain, database, or persistent volume is needed.

Variables:
- BTC_SCHEDULER_ENABLED=false until the secret is registered and deployment is ready
- PAPER_ONLY=true
- REAL_TRADING=false
- BTC_GITHUB_TOKEN: register directly as a Railway secret, never in Git or chat

Credential: GitHub fine-grained personal access token, restricted to this repository,
with Actions read/write and a limited expiration. Contents write is not required.
This permission is repository-scoped, not restricted to a single workflow; the script
itself locks the repository/workflow. The ChatGPT GitHub connector does not supply an
exportable token for this server.

After setup, enable BTC_SCHEDULER_ENABLED=true and verify a workflow_dispatch run,
its safety checks and persisted adaptive-meta.json. Observe at least three consecutive
intervals before claiming regular collection. Keep GitHub cron as a fallback.
Railway costs and account selection must be confirmed before activating a new service.

References:
https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
https://docs.railway.com/guides/cron-workers-queues#cron-jobs

Tests: python -m unittest discover -s btc-flow-monitor -p 'test_*.py' -v
