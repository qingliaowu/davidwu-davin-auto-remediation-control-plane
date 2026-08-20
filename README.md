# Devin Autonomous Remediation Control Plane

An event-driven engineering control plane that converts approved GitHub issues into verified pull requests using Devin as an autonomous software engineer.

## Quick start

```bash
cp .env.example .env
pip install -e ".[dev]"
python -m auto_remediation.main
```

Open <http://127.0.0.1:8000/dashboard> for the dashboard and use `http://127.0.0.1:8000/webhook/github` as the GitHub webhook URL.

## Docker

Build and run with Docker Compose:

```bash
cp .env.example .env
# edit .env with your ARP_* values
docker compose up --build
```

The dashboard is available at <http://localhost:8000/dashboard>.

## Project layout

- `src/auto_remediation/main.py` — FastAPI webhook receiver
- `src/auto_remediation/control_plane.py` — issue-to-PR orchestration
- `src/auto_remediation/devin_client.py` — async Devin v3 API client
- `src/auto_remediation/dashboard.py` — web dashboard and `/api/events`
- `src/auto_remediation/store.py` — in-memory event store for the dashboard
- `src/auto_remediation/models.py` — domain models
- `src/auto_remediation/config.py` — environment-based settings
- `tests/` — unit tests
- `Dockerfile` / `docker-compose.yml` — container deployment

## Web endpoints

| Endpoint | Description |
| --- | --- |
| `GET /health` | Health check |
| `POST /webhook/github` | Receive GitHub issue events (verifies `x-hub-signature-256` HMAC) |
| `GET /dashboard` | HTML dashboard of recent dispatches |
| `GET /api/events` | JSON feed of recent dispatches |

## Configuration

All settings are read from environment variables with the `ARP_` prefix:

- `ARP_GITHUB_TOKEN`
- `ARP_GITHUB_APP_ID`
- `ARP_GITHUB_PRIVATE_KEY`
- `ARP_WEBHOOK_SECRET`
- `ARP_DEVIN_API_KEY`
- `ARP_DEVIN_ORG_ID`
- `ARP_DEVIN_BASE_URL` (default: `https://api.devin.ai/v3`)
- `ARP_DEVIN_CREATE_AS_USER_ID`
- `ARP_LISTEN_HOST` (default: `127.0.0.1`)
- `ARP_LISTEN_PORT`

## Development

```bash
ruff check src tests
ruff format --check src tests
pytest
```
