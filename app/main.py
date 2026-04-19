"""
AI Code Review Bot — FastAPI Application

A self-hosted, codebase-aware GitHub bot that triggers on every pull request,
analyzes the diff using a multi-agent LLM pipeline, and posts structured,
severity-classified review comments back via the GitHub API.

Entry point: uvicorn app.main:app --reload
"""

from dotenv import load_dotenv
load_dotenv()

import json
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.github.webhook import parse_pr_event, validate_webhook_signature

# ---------------------------------------------------------------------------
# Environment & Logging Setup
# ---------------------------------------------------------------------------


# Configure structured logging with a consistent format across the application
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("app")


# ---------------------------------------------------------------------------
# Application Lifespan — startup / shutdown hooks
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages application lifecycle events.

    Startup:
        - Log application boot information
        - (Future) Initialize DB connection pool, Redis, Celery, ChromaDB

    Shutdown:
        - (Future) Gracefully close connections
    """
    logger.info("🚀 AI Code Review Bot starting up...")
    logger.info("   Environment loaded from .env")
    yield
    logger.info("🛑 AI Code Review Bot shutting down...")


# ---------------------------------------------------------------------------
# FastAPI Application Instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI Code Review Bot",
    description=(
        "A self-hosted, multi-agent AI code review bot that analyzes GitHub PRs "
        "using specialized LLM agents (Security, Performance, Logic, Style) and "
        "posts severity-classified inline comments via the GitHub API."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

# CORS — permissive in development; tighten origins for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health Check Endpoint
# ---------------------------------------------------------------------------

@app.get(
    "/ping",
    tags=["Health"],
    summary="Health check",
    response_description="Returns status ok when the service is running",
)
async def ping():
    """
    Lightweight health-check endpoint.

    Returns a simple JSON payload confirming the service is alive.
    Used by load balancers, Docker health checks, and monitoring tools.
    """
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# GitHub Webhook Endpoint
# ---------------------------------------------------------------------------

@app.post(
    "/webhook/github",
    tags=["Webhook"],
    summary="Receive GitHub PR events",
    response_description="Acknowledgement that the event was received",
)
async def github_webhook(request: Request):
    """
    Receives and processes GitHub Pull Request webhook events.

    Flow:
        1. Validate the HMAC-SHA256 signature (reject tampered payloads)
        2. Parse the JSON body and extract PR metadata
        3. Filter: only ``opened`` and ``synchronize`` actions are processed
        4. (Future) Enqueue a Celery task for async review processing
        5. Return 200 immediately so GitHub doesn't time out

    The webhook should be configured on the GitHub App / repo to fire on
    **Pull Request** events only.
    """
    # Step 1: Validate signature — raises 400/403 on failure
    body = await validate_webhook_signature(request)

    # Step 2: Parse payload
    payload = json.loads(body)

    # Check if this is a PR event
    event_type = request.headers.get("X-GitHub-Event", "")
    if event_type != "pull_request":
        logger.info("Ignoring non-PR event: %s", event_type)
        return {"status": "ignored", "reason": f"event type '{event_type}' not handled"}

    # Step 3: Extract and filter PR metadata
    pr_metadata = parse_pr_event(payload)

    if pr_metadata is None:
        return {"status": "ignored", "reason": "action not supported"}

    # Step 4: TODO (Sprint 4+) — Enqueue Celery task for async review
    # For now, log the metadata so we can verify the pipeline works
    logger.info(
        "✅ Webhook processed — PR #%s ready for review (will enqueue in Sprint 4)",
        pr_metadata["pr_number"],
    )

    return {
        "status": "received",
        "pr_number": pr_metadata["pr_number"],
        "repo": f"{pr_metadata['repo_owner']}/{pr_metadata['repo_name']}",
        "action": pr_metadata["action"],
    }

