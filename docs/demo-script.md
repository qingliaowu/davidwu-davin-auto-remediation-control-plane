# Demo Script (under five minutes)

This script demonstrates the control plane locally with dry-run mode.

## Setup (30 seconds)

```bash
cd /home/ubuntu/repos/davidwu-davin-auto-remediation-control-plane
cp .env.example .env
# Edit .env
GITHUB_WEBHOOK_SECRET=test-secret
GITHUB_ALLOWED_REPOSITORY=qingliaowu/superset
DEVIN_DRY_RUN=true
```

## Start the service (30 seconds)

```bash
.venv/bin/uvicorn auto_remediation.main:app --host 127.0.0.1 --port 8000
```

Verify health:

```bash
curl http://127.0.0.1:8000/health
```

## Send a signed dry-run webhook (1 minute)

```bash
.venv/bin/python scripts/simulate_webhook.py \
    --issue-number 42 \
    --issue-title "Fix login redirect" \
    --repository qingliaowu/superset \
    --secret test-secret
```

Expected output:

```text
Sending single signed webhook(s) to http://127.0.0.1:8000/webhooks/github
Repository: qingliaowu/superset
Issue: #42 Fix login redirect
Delivery ID: <uuid>
Attempt 1: 202 {"status":"eligible","task_id":"..."}
```

## Show the dashboard (30 seconds)

Open `http://127.0.0.1:8000/dashboard` in a browser.

- Cards show 1 event received, 1 eligible task, 1 Devin session, 1 active task, 0.00 ACUs.
- The recent-task table shows `#42 Fix login redirect` with a `DRY RUN` badge.

Click the task ID to open the detail page and see the issue metadata, state timeline, mock session link, and structured output.

## Demonstrate duplicate-event idempotency (1 minute)

Run the simulator again with `--duplicate`:

```bash
.venv/bin/python scripts/simulate_webhook.py \
    --issue-number 42 \
    --issue-title "Fix login redirect" \
    --duplicate
```

Expected output:

```text
Attempt 1: 202 {"status":"eligible","task_id":"..."}
Attempt 2: 200 {"status":"duplicate","delivery_id":"..."}
```

Only one task exists. `/metrics` shows `duplicate_attempts: 1`.

## Show metrics (30 seconds)

```bash
curl http://127.0.0.1:8000/metrics | jq .
```

Highlight:

- `webhook_delivery_attempts: 3`
- `unique_webhook_deliveries: 2`
- `eligible_tasks: 1`
- `duplicate_attempts: 1`
- `devin_sessions_created: 1`

## Docker one-liner (30 seconds, optional)

```bash
docker compose up --build -d
curl -f http://127.0.0.1:8000/health
```

Stop with `docker compose down`.

## Closing

> The control plane governs the work. Devin performs the engineering.

This local dry-run proves signature validation, eligibility, idempotency, task creation, mock Devin dispatch, and observability — all without a real Devin API call.
