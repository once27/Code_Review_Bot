"""
Test script for the GitHub webhook endpoint.

Simulates GitHub webhook requests with proper HMAC-SHA256 signatures
to verify the endpoint works correctly before connecting to real GitHub.

Usage:
    python -m tests.test_webhook

Tests:
    1. Valid PR opened event → 200 with "received"
    2. Missing signature header → 400
    3. Invalid signature → 403
    4. Non-PR event type → 200 with "ignored"
    5. Unsupported PR action (e.g., "closed") → 200 with "ignored"
"""

import hashlib
import hmac
import json
import os
import sys

from dotenv import load_dotenv

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")

WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "your_webhook_secret_here")

# Sample PR payload matching GitHub's webhook format
SAMPLE_PR_PAYLOAD = {
    "action": "opened",
    "number": 42,
    "pull_request": {
        "title": "Add input validation to login endpoint",
        "user": {"login": "developer123"},
        "head": {"sha": "abc123def456789"},
        "base": {"ref": "main"},
    },
    "repository": {
        "name": "my-awesome-app",
        "owner": {"login": "octocat"},
    },
}


def compute_signature(payload_bytes: bytes, secret: str) -> str:
    """Compute the HMAC-SHA256 signature matching GitHub's format."""
    return "sha256=" + hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()


def test_valid_pr_opened():
    """Test: Valid PR opened event should return 200 with 'received' status."""
    payload_bytes = json.dumps(SAMPLE_PR_PAYLOAD).encode("utf-8")
    signature = compute_signature(payload_bytes, WEBHOOK_SECRET)

    response = requests.post(
        f"{BASE_URL}/webhook/github",
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "pull_request",
        },
    )

    print(f"Test 1 — Valid PR opened event")
    print(f"  Status: {response.status_code}")
    print(f"  Body:   {response.json()}")
    assert response.status_code == 200
    assert response.json()["status"] == "received"
    assert response.json()["pr_number"] == 42
    print("  ✅ PASSED\n")


def test_missing_signature():
    """Test: Missing signature header should return 400."""
    payload_bytes = json.dumps(SAMPLE_PR_PAYLOAD).encode("utf-8")

    response = requests.post(
        f"{BASE_URL}/webhook/github",
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
        },
    )

    print(f"Test 2 — Missing signature header")
    print(f"  Status: {response.status_code}")
    assert response.status_code == 400
    print("  ✅ PASSED\n")


def test_invalid_signature():
    """Test: Invalid signature should return 403."""
    payload_bytes = json.dumps(SAMPLE_PR_PAYLOAD).encode("utf-8")

    response = requests.post(
        f"{BASE_URL}/webhook/github",
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=invalid_signature_here",
            "X-GitHub-Event": "pull_request",
        },
    )

    print(f"Test 3 — Invalid signature")
    print(f"  Status: {response.status_code}")
    assert response.status_code == 403
    print("  ✅ PASSED\n")


def test_non_pr_event():
    """Test: Non-PR event (e.g., push) should be ignored."""
    payload_bytes = json.dumps({"ref": "refs/heads/main"}).encode("utf-8")
    signature = compute_signature(payload_bytes, WEBHOOK_SECRET)

    response = requests.post(
        f"{BASE_URL}/webhook/github",
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "push",
        },
    )

    print(f"Test 4 — Non-PR event (push)")
    print(f"  Status: {response.status_code}")
    print(f"  Body:   {response.json()}")
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    print("  ✅ PASSED\n")


def test_unsupported_pr_action():
    """Test: Unsupported PR action (e.g., 'closed') should be ignored."""
    payload = {**SAMPLE_PR_PAYLOAD, "action": "closed"}
    payload_bytes = json.dumps(payload).encode("utf-8")
    signature = compute_signature(payload_bytes, WEBHOOK_SECRET)

    response = requests.post(
        f"{BASE_URL}/webhook/github",
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "pull_request",
        },
    )

    print(f"Test 5 — Unsupported PR action (closed)")
    print(f"  Status: {response.status_code}")
    print(f"  Body:   {response.json()}")
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    print("  ✅ PASSED\n")


def test_synchronize_action():
    """Test: synchronize action (new commits pushed) should be processed."""
    payload = {**SAMPLE_PR_PAYLOAD, "action": "synchronize"}
    payload_bytes = json.dumps(payload).encode("utf-8")
    signature = compute_signature(payload_bytes, WEBHOOK_SECRET)

    response = requests.post(
        f"{BASE_URL}/webhook/github",
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "pull_request",
        },
    )

    print(f"Test 6 — Synchronize action (new commits)")
    print(f"  Status: {response.status_code}")
    print(f"  Body:   {response.json()}")
    assert response.status_code == 200
    assert response.json()["status"] == "received"
    print("  ✅ PASSED\n")


if __name__ == "__main__":
    print("=" * 60)
    print("  GitHub Webhook Endpoint Tests")
    print("=" * 60)
    print(f"  Target: {BASE_URL}/webhook/github")
    print(f"  Secret: {WEBHOOK_SECRET[:8]}...")
    print("=" * 60 + "\n")

    tests = [
        test_valid_pr_opened,
        test_missing_signature,
        test_invalid_signature,
        test_non_pr_event,
        test_unsupported_pr_action,
        test_synchronize_action,
    ]

    passed = 0
    failed = 0

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except (AssertionError, Exception) as e:
            print(f"  ❌ FAILED: {e}\n")
            failed += 1

    print("=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)

    sys.exit(1 if failed > 0 else 0)
