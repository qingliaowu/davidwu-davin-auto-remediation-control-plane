# Devin Autonomous Remediation Control Plane

An event-driven engineering control plane that converts approved GitHub issues into verified pull requests using Devin as an autonomous software engineer.

## Quick start

```bash
cp .env.example .env
pip install -e ".[dev]"
python -m auto_remediation.main
```

## Project layout

- `src/auto_remediation/main.py` — FastAPI webhook receiver
- `src/auto_remediation/control_plane.py` — issue-to-PR orchestration
- `src/auto_remediation/devin_client.py` — async Devin v3 API client
- `src/auto_remediation/models.py` — domain models
- `src/auto_remediation/config.py` — environment-based settings
- `tests/` — placeholder tests

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
- `ARP_LISTEN_HOST`
- `ARP_LISTEN_PORT`
