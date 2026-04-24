"""
GitHub API Client — Diff Extraction & Repository Access

Wraps PyGitHub to provide structured access to Pull Request diffs and
repository file content. Designed for use by the review pipeline.

Usage:
    client = GitHubClient()
    diffs = client.get_pr_diff("octocat", "my-repo", 42)
"""

import logging
import os
import re
from dataclasses import dataclass, field

from github import Github, GithubException

logger = logging.getLogger("app.github.client")

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FileDiff:
    """
    Represents a single file's diff within a Pull Request.

    Attributes:
        filename:          Path of the changed file relative to repo root.
        status:            One of: added, modified, removed, renamed, copied.
        additions:         Number of lines added.
        deletions:         Number of lines deleted.
        patch:             Raw unified diff text (empty string for binary files).
        previous_filename: Original path if the file was renamed, else None.
    """
    filename: str
    status: str
    additions: int
    deletions: int
    patch: str
    previous_filename: str | None = None


# ---------------------------------------------------------------------------
# File Filtering
# ---------------------------------------------------------------------------

# Lock / dependency files that add noise to reviews
SKIP_FILENAMES: set[str] = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "composer.lock",
    "Gemfile.lock",
    "cargo.lock",
    "go.sum",
}

# Directory prefixes to ignore
SKIP_DIRECTORIES: tuple[str, ...] = (
    "vendor/",
    "node_modules/",
    ".git/",
    "__pycache__/",
    ".venv/",
    "venv/",
)

# File extensions that are generated / non-reviewable
SKIP_EXTENSIONS: set[str] = {
    ".min.js",
    ".min.css",
    ".map",
    ".pyc",
    ".pyo",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".ico",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
}


def _should_skip_file(filename: str) -> bool:
    """
    Determine whether a file should be excluded from review.

    Skips binary files, lock files, generated assets, and vendored code.
    """
    basename = os.path.basename(filename).lower()

    # Exact filename match (lock files)
    if basename in {name.lower() for name in SKIP_FILENAMES}:
        return True

    # Directory prefix match
    if any(filename.lower().startswith(d) for d in SKIP_DIRECTORIES):
        return True

    # Extension match — check compound extensions like .min.js
    lower = filename.lower()
    if any(lower.endswith(ext) for ext in SKIP_EXTENSIONS):
        return True

    return False


# ---------------------------------------------------------------------------
# GitHub Client
# ---------------------------------------------------------------------------

class GitHubClient:
    """
    Thin wrapper around PyGitHub for Pull Request diff extraction.

    Reads ``GITHUB_TOKEN`` from environment. Token needs ``repo`` scope
    (or ``public_repo`` for public repos).
    """

    def __init__(self, token: str | None = None):
        self._token = token or os.getenv("GITHUB_TOKEN", "")
        if not self._token:
            raise ValueError(
                "GITHUB_TOKEN not set. Provide token or set env variable."
            )
        self._github = Github(self._token)
        logger.debug("GitHubClient initialized")

    def get_pr_diff(
        self,
        owner: str,
        repo_name: str,
        pr_number: int,
        *,
        max_files: int = 50,
    ) -> list[FileDiff]:
        """
        Fetch and parse the diff for a Pull Request.

        Args:
            owner:      Repository owner (user or org).
            repo_name:  Repository name.
            pr_number:  Pull request number.
            max_files:  Safety cap on number of files to process.

        Returns:
            List of ``FileDiff`` objects for reviewable files.

        Raises:
            GithubException: On API errors (auth, not found, rate limit).
        """
        full_name = f"{owner}/{repo_name}"
        logger.info("Fetching diff for PR #%d on %s", pr_number, full_name)

        try:
            repo = self._github.get_repo(full_name)
            pr = repo.get_pull(pr_number)
        except GithubException as exc:
            logger.error(
                "GitHub API error fetching PR #%d on %s: %s",
                pr_number, full_name, exc,
            )
            raise

        files = pr.get_files()
        diffs: list[FileDiff] = []
        skipped: list[str] = []

        for i, f in enumerate(files):
            if i >= max_files:
                logger.warning(
                    "PR #%d has %d+ files — capping at %d",
                    pr_number, i, max_files,
                )
                break

            # Skip non-reviewable files
            if _should_skip_file(f.filename):
                skipped.append(f.filename)
                continue

            # Binary files have no patch from GitHub API
            patch = f.patch or ""
            if not patch and f.status != "removed":
                skipped.append(f.filename)
                continue

            diff = FileDiff(
                filename=f.filename,
                status=f.status,
                additions=f.additions,
                deletions=f.deletions,
                patch=patch,
                previous_filename=f.previous_filename,
            )
            diffs.append(diff)

        logger.info(
            "PR #%d diff: %d reviewable files, %d skipped %s",
            pr_number,
            len(diffs),
            len(skipped),
            skipped if skipped else "",
        )
        return diffs

    def get_file_content(
        self,
        owner: str,
        repo_name: str,
        path: str,
        ref: str = "main",
    ) -> str | None:
        """
        Fetch raw content of a single file from the repository.

        Useful for RAG indexing and context retrieval in later sprints.

        Args:
            owner:     Repository owner.
            repo_name: Repository name.
            path:      File path relative to repo root.
            ref:       Branch or commit SHA to read from.

        Returns:
            Decoded file content as string, or None on error.
        """
        full_name = f"{owner}/{repo_name}"
        try:
            repo = self._github.get_repo(full_name)
            content = repo.get_contents(path, ref=ref)

            # get_contents returns a list for directories
            if isinstance(content, list):
                logger.warning("Path '%s' is a directory, not a file", path)
                return None

            return content.decoded_content.decode("utf-8")
        except GithubException as exc:
            logger.error(
                "Failed to fetch %s from %s@%s: %s",
                path, full_name, ref, exc,
            )
            return None

    def post_review(
        self,
        owner: str,
        repo_name: str,
        pr_number: int,
        commit_sha: str,
        comments: list[dict],
        summary: str | None = None,
    ) -> None:
        """
        Post a bundle of review comments to a Pull Request as a single Review.

        Args:
            owner:      Repository owner.
            repo_name:  Repository name.
            pr_number:  Pull request number.
            commit_sha: The SHA of the commit being reviewed (important!).
            comments:   List of dicts with: {path, line, body, [side]}.
            summary:    Optional PR-level summary text.
        """
        full_name = f"{owner}/{repo_name}"
        logger.info(
            "Posting review with %d comments on PR #%d (%s)",
            len(comments), pr_number, full_name,
        )

        try:
            repo = self._github.get_repo(full_name)
            pr = repo.get_pull(pr_number)

            # Map to PyGitHub expected format
            # Side 'RIGHT' targets the new code in the PR
            github_comments = []
            for c in comments:
                github_comments.append({
                    "path": c["path"],
                    "line": int(c["line"]),
                    "body": c["body"],
                    "side": c.get("side", "RIGHT"),
                })

            pr.create_review(
                commit=repo.get_commit(commit_sha),
                body=summary or "AI Code Review completed.",
                event="COMMENT",
                comments=github_comments,
            )
            logger.info("Review posted successfully to PR #%d", pr_number)

        except GithubException as exc:
            logger.error(
                "Failed to post review to PR #%d on %s: %s",
                pr_number, full_name, exc,
            )
            

