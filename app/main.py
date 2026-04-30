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
from app.github.client import GitHubClient
from app.github.diff_formatter import format_diff_for_llm, format_diff_summary
from app.agents.pipeline import run_review_pipeline
from app.db.session import init_db
from app.db.crud import save_review
from app.rag.indexer import index_repository
from app.rag.retriever import retrieve_context

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

# Severity Emojis for feedback
SEVERITY_EMOJI = {
    "critical": "🔴",
    "warning": "🟡",
    "suggestion": "💡",
}


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
    logger.info("AI Code Review Bot starting up...")
    logger.info("   Environment loaded from .env")

    # Initialize database tables
    try:
        init_db()
    except Exception as exc:
        logger.warning("DB init failed (non-fatal): %s", exc)

    yield
    logger.info("AI Code Review Bot shutting down...")


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
# Repository Index Endpoint
# ---------------------------------------------------------------------------

@app.post(
    "/repos/index",
    tags=["RAG"],
    summary="Index a repository for RAG context",
    response_description="Indexing statistics",
)
async def index_repo(owner: str, repo_name: str, branch: str | None = None):
    """
    Trigger codebase indexing for a repository.

    Clones the repo, chunks Python files, embeds them, and stores
    in ChromaDB for RAG-powered context retrieval during reviews.

    Query params:
        owner:     Repository owner (e.g., "once27")
        repo_name: Repository name (e.g., "test-review-bot")
        branch:    Optional branch to index (defaults to repo default branch)
    """
    logger.info("Indexing requested for %s/%s (branch: %s)", owner, repo_name, branch)
    stats = index_repository(owner, repo_name, branch)
    return stats


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

    # Step 4: Fetch PR diff from GitHub API
    diff_summary = None
    try:
        client = GitHubClient()
        diffs = client.get_pr_diff(
            owner=pr_metadata["repo_owner"],
            repo_name=pr_metadata["repo_name"],
            pr_number=pr_metadata["pr_number"],
        )

        # Step 4b: Fetch repo config
        review_config = client.fetch_review_config(
            owner=pr_metadata["repo_owner"],
            repo_name=pr_metadata["repo_name"],
            ref=pr_metadata.get("head_sha", "main"),
        )
        logger.info(
            "Review config loaded — agents=%s, threshold=%s, ignore=%d patterns, rules=%d",
            review_config.enabled_agents,
            review_config.threshold,
            len(review_config.ignore),
            len(review_config.custom_rules),
        )

        # Filter diffs by ignore patterns from config
        if review_config.ignore:
            original_count = len(diffs)
            diffs = [d for d in diffs if review_config.should_review_file(d.filename)]
            if len(diffs) < original_count:
                logger.info(
                    "Config ignore patterns filtered %d files (kept %d)",
                    original_count - len(diffs), len(diffs),
                )

        # Format for LLM consumption
        formatted_diff = format_diff_for_llm(diffs)
        diff_summary = format_diff_summary(diffs)

        logger.info(
            "Diff extracted — %d files, +%d -%d lines",
            diff_summary["total_files"],
            diff_summary["total_additions"],
            diff_summary["total_deletions"],
        )
        logger.debug("Formatted diff for LLM:\n%s", formatted_diff[:500])

    except Exception as exc:
        # Diff fetch failure should not cause webhook to fail.
        # GitHub would retry on non-200 responses, causing duplicate processing.
        logger.error(
            "Failed to fetch diff for PR #%s: %s",
            pr_metadata["pr_number"],
            exc,
        )
        review_config = None

    # Step 5: Retrieve RAG codebase context
    codebase_context = None
    if diff_summary:
        try:
            repo_key = f"{pr_metadata['repo_owner']}/{pr_metadata['repo_name']}"
            base_branch = pr_metadata.get("base_branch")
            codebase_context = retrieve_context(
                formatted_diff, repo_key, branch=base_branch
            )
            if codebase_context:
                logger.info("RAG context retrieved (%d chars)", len(codebase_context))
        except Exception as exc:
            logger.warning("RAG retrieval failed (non-fatal): %s", exc)

    # Step 6: Run multi-agent review pipeline
    review_comments = []
    if diff_summary and formatted_diff:
        try:
            pipeline_kwargs = {}
            if review_config:
                pipeline_kwargs = {
                    "enabled_agents": review_config.enabled_agents,
                    "threshold": review_config.threshold,
                    "max_comments": review_config.max_comments,
                    "custom_rules": review_config.custom_rules,
                }
            if codebase_context:
                pipeline_kwargs["codebase_context"] = codebase_context

            review_comments = await run_review_pipeline(
                formatted_diff, **pipeline_kwargs
            )

            for comment in review_comments:
                logger.info(
                    "💬 [%s|%s] %s:%d — %s",
                    comment.severity.upper(),
                    comment.agent_type,
                    comment.file,
                    comment.line,
                    comment.message,
                )

        except Exception as exc:
            logger.error(
                "Pipeline review failed for PR #%s: %s",
                pr_metadata["pr_number"],
                exc,
            )

    logger.info(
        "PR #%s processed — diff %s, %d review comments",
        pr_metadata["pr_number"],
        "extracted" if diff_summary else "failed",
        len(review_comments),
    )

    if diff_summary and review_comments:
        try:
            # Count severities
            counts = {"critical": 0, "warning": 0, "suggestion": 0}
            for c in review_comments:
                counts[c.severity] = counts.get(c.severity, 0) + 1

            has_critical = counts["critical"] > 0

            # Determine review event type 
            if has_critical:
                review_event = "REQUEST_CHANGES"
                header = "### AI Code Review — Changes Requested"
                status_line = (
                    f"Found **{counts['critical']} critical** issue(s) "
                    f"that must be resolved before merging."
                )
            else:
                review_event = "COMMENT"
                header = "### AI Code Review Summary"
                status_line = (
                    f"Analyzed **{diff_summary['total_files']}** file(s). "
                    f"Found **{len(review_comments)}** potential issue(s)."
                )

            summary_parts = [header, status_line, "\n**Breakdown:**"]
            if counts["critical"]:
                summary_parts.append(f"- 🔴 {counts['critical']} Critical")
            if counts["warning"]:
                summary_parts.append(f"- 🟡 {counts['warning']} Warnings")
            if counts["suggestion"]:
                summary_parts.append(f"- 💡 {counts['suggestion']} Suggestions")

            summary_text = "\n".join(summary_parts)

            logger.info(
                "Review event: %s (critical=%d, warning=%d, suggestion=%d)",
                review_event, counts["critical"], counts["warning"], counts["suggestion"],
            )

            # Map comments to GitHub format
            github_comments = []
            for c in review_comments:
                emoji = SEVERITY_EMOJI.get(c.severity, "💬")
                github_comments.append({
                    "path": c.file,
                    "line": c.line,
                    "body": f"### {emoji} {c.severity.upper()}\n\n{c.message}"
                })

            client.post_review(
                owner=pr_metadata["repo_owner"],
                repo_name=pr_metadata["repo_name"],
                pr_number=pr_metadata["pr_number"],
                commit_sha=pr_metadata["head_sha"],
                comments=github_comments,
                summary=summary_text,
                event=review_event,
            )

            # Step 7: Save review to database
            try:
                save_review(
                    repo_owner=pr_metadata["repo_owner"],
                    repo_name=pr_metadata["repo_name"],
                    pr_number=pr_metadata["pr_number"],
                    pr_author=pr_metadata.get("pr_author"),
                    commit_sha=pr_metadata["head_sha"],
                    event_type=review_event,
                    comments=review_comments,
                    agents_used=review_config.enabled_agents if review_config else None,
                    threshold=review_config.threshold if review_config else None,
                )
            except Exception as exc:
                logger.error("Failed to save review to DB: %s", exc)

        except Exception as exc:
            logger.error("Failed to post GitHub review: %s", exc)

    response = {
        "status": "received",
        "pr_number": pr_metadata["pr_number"],
        "repo": f"{pr_metadata['repo_owner']}/{pr_metadata['repo_name']}",
        "action": pr_metadata["action"],
    }
    if diff_summary:
        response["diff_summary"] = diff_summary
    if review_comments:
        response["review_comments"] = [
            {
                "file": c.file,
                "line": c.line,
                "severity": c.severity,
                "message": c.message,
                "agent": c.agent_type,
            }
            for c in review_comments
        ]

    return response

