# Devin Autonomous Remediation Control Plane — Phase 1

Phase 1 implements the core webhook ingestion, eligibility policy, persistent event tracking, and durable task creation for the control plane.

## Technology Stack

- Python 3.12
- FastAPI
- SQLAlchemy 2 (async) + SQLite via `aiosqlite`
- Pydantic Settings
- Pytest

## Running the Server

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Required environment variables
export GITHUB_WEBHOOK_SECRET="your-secret"
export GITHUB_ALLOWED_REPOSITORY="owner/repo"

python -m auto_remediation.main
```

The server listens on `127.0.0.1:8000` by default.

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Health check |
| POST | `/webhooks/github` | Receive and process GitHub webhooks |
| GET | `/tasks` | List remediation tasks |
| GET | `/tasks/{task_id}` | Get a single remediation task |

## Webhook Behavior

- The raw HTTP request body is verified against `X-Hub-Signature-256` using HMAC-SHA256 and `hmac.compare_digest`.
- Only `issues` events with `action=labeled`, `label.name=devin-fix`, `issue.state=open`, and `repository.full_name=GITHUB_ALLOWED_REPOSITORY` are eligible.
- Eligible events create a `RemediationTask` with status `QUEUED` and return `202 Accepted`.
- Ineligible events are recorded but return `200 OK` with an ignored reason.
- Duplicate `X-GitHub-Delivery` values increment `attempt_count` and return `200 OK` without creating another task.
- Invalid signatures return `401 Unauthorized`; malformed JSON returns `400 Bad Request`.

## Database Design

### `webhook_deliveries`

| Column | Notes |
| --- | --- |
| `id` | Primary key |
| `github_delivery_id` | Unique GitHub delivery ID |
| `event_name` | `X-GitHub-Event` header value |
| `action` | Payload action |
| `repository` | `owner/repo` |
| `issue_number` | Issue number when available |
| `outcome` | `eligible`, `ignored`, or `duplicate` |
| `ignored_reason` | Why the event was ignored |
| `attempt_count` | Starts at 1, increments for duplicates |
| `received_at` | UTC timestamp |

### `remediation_tasks`

| Column | Notes |
| --- | --- |
| `id` | Primary key |
| `task_id` | Unique UUID |
| `webhook_delivery_id` | FK to `webhook_deliveries.id` |
| `repository` | `owner/repo` |
| `issue_number` | Issue number |
| `issue_title` | Issue title |
| `issue_body` | Issue body |
| `issue_url` | Issue URL |
| `target_branch` | Target branch for remediation |
| `triggering_label` | Label that triggered the task |
| `status` | One of the defined task states |
| `dry_run` | Boolean dry-run flag |
| `received_at` | UTC timestamp |
| `queued_at` | UTC timestamp when queued |
| `error_code` | Error code on failure |
| `error_message` | Error message on failure |

### Task States

- `QUEUED`
- `DISPATCHING`
- `RUNNING`
- `WAITING_FOR_USER`
- `WAITING_FOR_APPROVAL`
- `SUCCEEDED`
- `FAILED`

## Signature Verification

1. Read the raw request body before JSON parsing.
2. Read the `X-Hub-Signature-256` header.
3. Compute `HMAC-SHA256(secret, body).hexdigest()`.
4. Compare using `hmac.compare_digest` to prevent timing attacks.

## Idempotency

The `github_delivery_id` from the `X-GitHub-Delivery` header has a unique database constraint. The first delivery inserts a `WebhookDelivery` row and, if eligible, creates one `RemediationTask`. Subsequent deliveries with the same ID increment `attempt_count` and return a `duplicate` response without creating a new task.

## Development

```bash
ruff check src tests
ruff format --check src tests
pytest -q
```
