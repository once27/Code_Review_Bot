"""
AI Code Review Bot — FastAPI Application

A self-hosted, codebase-aware GitHub bot that triggers on every pull request,
analyzes the diff using a multi-agent LLM pipeline, and posts structured,
severity-classified review comments back via the GitHub API.

Entry point: uvicorn app.main:app --reload
"""

import logging
import sys
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Environment & Logging Setup
# ---------------------------------------------------------------------------

load_dotenv()

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
