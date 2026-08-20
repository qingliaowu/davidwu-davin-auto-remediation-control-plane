"""HTTP entry point for the auto-remediation control plane."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auto_remediation.config import settings
from auto_remediation.database import db, get_db
from auto_remediation.devin_client import DevinClient
from auto_remediation.services import (
    get_task,
    handle_github_event,
    list_tasks,
    verify_signature,
)
from auto_remediation.worker import Worker

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create database tables and start the background worker when configured."""
    await db.setup()

    worker_enabled = bool(settings.devin_api_key) or settings.devin_dry_run
    if worker_enabled:
        app.state.worker = Worker(db, DevinClient())
        await app.state.worker.start()
    else:
        logging.warning("Background worker not started: set DEVIN_API_KEY or DEVIN_DRY_RUN=true")

    yield

    worker = getattr(app.state, "worker", None)
    if worker:
        await worker.stop()


app = FastAPI(
    title="Auto Remediation Control Plane",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/webhooks/github")
async def github_webhook(request: Request, session: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Receive and process verified GitHub issue events."""
    secret = settings.github_webhook_secret
    if not secret:
        raise HTTPException(status_code=401, detail="Webhook secret not configured")

    signature = request.headers.get("x-hub-signature-256")
    body = await request.body()
    if not verify_signature(body, secret, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Malformed JSON") from exc

    event_name = request.headers.get("x-github-event")
    delivery_id = request.headers.get("x-github-delivery")

    result = await handle_github_event(session, event_name, delivery_id, payload)
    return JSONResponse(content=result.body, status_code=result.status_code)


@app.get("/tasks")
async def tasks(session: AsyncSession = Depends(get_db)) -> dict[str, list[dict[str, Any]]]:
    """List all remediation tasks."""
    tasks = await list_tasks(session)
    return {"tasks": [task.to_dict() for task in tasks]}


@app.get("/tasks/{task_id}")
async def task_detail(task_id: str, session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Fetch a single remediation task by task_id."""
    task = await get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port)
