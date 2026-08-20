"""Dashboard routes for the control plane."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from auto_remediation.store import store

router = APIRouter()
_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Any:
    """Redirect root to dashboard."""
    return await dashboard(request)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> Any:
    """Render the remediation dashboard."""
    events = await store.list()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"events": events},
    )


@router.get("/api/events")
async def api_events() -> dict[str, list[dict[str, Any]]]:
    """Return recent remediation events as JSON."""
    return {"events": await store.list()}
