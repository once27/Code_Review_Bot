"""
GitHub OAuth helper for Streamlit dashboard authentication.

Handles the OAuth code exchange flow:
1. Generate authorization URL → redirect user to GitHub
2. Exchange callback code for access token
3. Fetch authenticated user info from GitHub API
"""

import os
import logging

import httpx

logger = logging.getLogger("app.auth.github_oauth")

GITHUB_OAUTH_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID", "")
GITHUB_OAUTH_CLIENT_SECRET = os.getenv("GITHUB_OAUTH_CLIENT_SECRET", "")

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


def get_authorization_url(redirect_uri: str) -> str:
    """
    Build the GitHub OAuth authorization URL.

    Args:
        redirect_uri: Where GitHub sends the user after auth.

    Returns:
        Full URL to redirect the user to.
    """
    return (
        f"{GITHUB_AUTHORIZE_URL}"
        f"?client_id={GITHUB_OAUTH_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=read:user"
    )


def exchange_code_for_token(code: str) -> str | None:
    """
    Exchange the OAuth callback code for an access token.

    Args:
        code: The code parameter from GitHub's callback.

    Returns:
        Access token string, or None if exchange failed.
    """
    try:
        resp = httpx.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": GITHUB_OAUTH_CLIENT_ID,
                "client_secret": GITHUB_OAUTH_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
            timeout=10.0,
        )
        data = resp.json()

        token = data.get("access_token")
        if not token:
            logger.error("OAuth token exchange failed: %s", data)
            return None

        return token

    except Exception as exc:
        logger.error("OAuth token exchange error: %s", exc)
        return None


def get_github_user(token: str) -> dict | None:
    """
    Fetch the authenticated user's profile from GitHub.

    Args:
        token: GitHub access token.

    Returns:
        Dict with 'login', 'id', 'avatar_url', or None if failed.
    """
    try:
        resp = httpx.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=10.0,
        )

        if resp.status_code != 200:
            logger.error("GitHub user API failed: %d", resp.status_code)
            return None

        data = resp.json()
        return {
            "login": data["login"],
            "id": data["id"],
            "avatar_url": data.get("avatar_url", ""),
        }

    except Exception as exc:
        logger.error("GitHub user fetch error: %s", exc)
        return None
