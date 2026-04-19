"""
GitHub Webhook Signature Validation

Validates incoming GitHub webhook payloads using HMAC-SHA256.
GitHub signs every webhook payload with the secret configured on the
GitHub App / repository webhook. We recompute the hash on our end
and reject any request where the signatures don't match.

Reference: https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
"""

import hashlib
import hmac
import logging
import os

from fastapi import HTTPException, Request

logger = logging.getLogger("app.github.webhook")

# ---------------------------------------------------------------------------
# Signature Validation
# ---------------------------------------------------------------------------

WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")


async def validate_webhook_signature(request: Request) -> bytes:
    """
    Validate the HMAC-SHA256 signature of an incoming GitHub webhook request.

    GitHub sends the signature in the ``X-Hub-Signature-256`` header as::

        sha256=<hex-digest>

    We compute the expected digest from the raw request body and the shared
    webhook secret, then use ``hmac.compare_digest`` (constant-time comparison)
    to prevent timing attacks.

    Args:
        request: The incoming FastAPI request object.

    Returns:
        The raw request body bytes (so we don't have to read the stream twice).

    Raises:
        HTTPException 400: If the signature header is missing.
        HTTPException 403: If the signature is invalid.
        HTTPException 500: If the webhook secret is not configured.
    """
    if not WEBHOOK_SECRET:
        logger.error("GITHUB_WEBHOOK_SECRET is not set in environment variables")
        raise HTTPException(
            status_code=500,
            detail="Webhook secret not configured on server",
        )

    # --- Read raw body (must happen before any JSON parsing) ---
    body = await request.body()

    # --- Extract the signature header ---
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        logger.warning("Webhook received without X-Hub-Signature-256 header")
        raise HTTPException(
            status_code=400,
            detail="Missing X-Hub-Signature-256 header",
        )

    # --- Compute expected signature ---
    expected_signature = (
        "sha256="
        + hmac.new(
            key=WEBHOOK_SECRET.encode("utf-8"),
            msg=body,
            digestmod=hashlib.sha256,
        ).hexdigest()
    )

    # --- Constant-time comparison to prevent timing attacks ---
    if not hmac.compare_digest(expected_signature, signature_header):
        logger.warning(
            "Webhook signature mismatch — possible tampering or wrong secret"
        )
        raise HTTPException(
            status_code=403,
            detail="Invalid webhook signature",
        )

    logger.debug("Webhook signature validated successfully")
    return body


# ---------------------------------------------------------------------------
# Event Parsing
# ---------------------------------------------------------------------------

def parse_pr_event(payload: dict) -> dict | None:
    """
    Extract the fields we need from a GitHub Pull Request webhook payload.

    We only care about two PR actions:
      - ``opened``      — a new PR was created
      - ``synchronize`` — new commits were pushed to an existing PR

    All other actions (closed, labeled, review_requested, etc.) are ignored.

    Args:
        payload: The parsed JSON body from the webhook POST.

    Returns:
        A dict with extracted PR metadata, or ``None`` if the event
        should be skipped (unhandled action type).

    Extracted fields::

        {
            "action":     "opened",
            "pr_number":  42,
            "repo_owner": "octocat",
            "repo_name":  "hello-world",
            "pr_author":  "developer123",
            "pr_title":   "Add login validation",
            "head_sha":   "abc123def456...",
            "base_branch": "main",
        }
    """
    SUPPORTED_ACTIONS = {"opened", "synchronize"}

    action = payload.get("action", "")

    if action not in SUPPORTED_ACTIONS:
        logger.info(
            "Ignoring PR event with action='%s' (only %s are processed)",
            action,
            SUPPORTED_ACTIONS,
        )
        return None

    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})

    pr_metadata = {
        "action": action,
        "pr_number": payload.get("number"),
        "repo_owner": repo.get("owner", {}).get("login", ""),
        "repo_name": repo.get("name", ""),
        "pr_author": pr.get("user", {}).get("login", ""),
        "pr_title": pr.get("title", ""),
        "head_sha": pr.get("head", {}).get("sha", ""),
        "base_branch": pr.get("base", {}).get("ref", ""),
    }

    logger.info(
        "📌 PR #%s by %s on %s/%s [%s] — %s",
        pr_metadata["pr_number"],
        pr_metadata["pr_author"],
        pr_metadata["repo_owner"],
        pr_metadata["repo_name"],
        pr_metadata["action"],
        pr_metadata["pr_title"],
    )

    return pr_metadata
