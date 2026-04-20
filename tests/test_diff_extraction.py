"""
Tests for Sprint 3 — Diff Extraction.

Unit tests using mocked PyGitHub objects (no actual GitHub API calls).
Run: python -m pytest tests/test_diff_extraction.py -v

Tests cover:
    1. FileDiff creation from mock data
    2. File filtering (lock files, binaries, generated assets)
    3. Diff formatter output structure
    4. Truncation when diff exceeds character limit
    5. Edge cases: empty PR, deleted file, renamed file
    6. GitHubClient.get_pr_diff with mocked PyGitHub
"""

import pytest
from unittest.mock import MagicMock, patch

from app.github.client import FileDiff, GitHubClient, _should_skip_file
from app.github.diff_formatter import (
    format_diff_for_llm,
    format_diff_summary,
    _format_single_file,
)


# ---------------------------------------------------------------------------
# FileDiff dataclass
# ---------------------------------------------------------------------------

class TestFileDiff:
    """Verify FileDiff dataclass construction and immutability."""

    def test_create_basic(self):
        diff = FileDiff(
            filename="app/views.py",
            status="modified",
            additions=10,
            deletions=3,
            patch="@@ -1,5 +1,7 @@\n+new line",
        )
        assert diff.filename == "app/views.py"
        assert diff.status == "modified"
        assert diff.additions == 10
        assert diff.deletions == 3
        assert diff.previous_filename is None

    def test_create_renamed(self):
        diff = FileDiff(
            filename="app/new_name.py",
            status="renamed",
            additions=0,
            deletions=0,
            patch="",
            previous_filename="app/old_name.py",
        )
        assert diff.previous_filename == "app/old_name.py"

    def test_frozen(self):
        diff = FileDiff("test.py", "added", 5, 0, "+line")
        with pytest.raises(AttributeError):
            diff.filename = "other.py"


# ---------------------------------------------------------------------------
# File Filtering
# ---------------------------------------------------------------------------

class TestFileFiltering:
    """Verify _should_skip_file correctly filters non-reviewable files."""

    @pytest.mark.parametrize("filename", [
        "package-lock.json",
        "yarn.lock",
        "poetry.lock",
        "Pipfile.lock",
        "pnpm-lock.yaml",
        "composer.lock",
        "Gemfile.lock",
        "cargo.lock",
        "go.sum",
    ])
    def test_skip_lock_files(self, filename):
        assert _should_skip_file(filename) is True

    @pytest.mark.parametrize("filename", [
        "vendor/lib/something.py",
        "node_modules/express/index.js",
        "__pycache__/module.cpython-311.pyc",
        ".git/config",
    ])
    def test_skip_directories(self, filename):
        assert _should_skip_file(filename) is True

    @pytest.mark.parametrize("filename", [
        "static/app.min.js",
        "static/style.min.css",
        "bundle.js.map",
        "image.png",
        "font.woff2",
        "doc.pdf",
        "archive.zip",
    ])
    def test_skip_generated_and_binary(self, filename):
        assert _should_skip_file(filename) is True

    @pytest.mark.parametrize("filename", [
        "app/views.py",
        "src/components/App.tsx",
        "README.md",
        "requirements.txt",
        "Dockerfile",
        "app/models/user.py",
        ".env.example",
    ])
    def test_keep_source_files(self, filename):
        assert _should_skip_file(filename) is False


# ---------------------------------------------------------------------------
# Diff Formatter
# ---------------------------------------------------------------------------

class TestDiffFormatter:
    """Verify format_diff_for_llm and format_diff_summary."""

    def _make_diff(self, filename="test.py", status="modified",
                   additions=5, deletions=2, patch="+new line\n-old line"):
        return FileDiff(filename, status, additions, deletions, patch)

    def test_format_single_modified(self):
        diff = self._make_diff()
        result = _format_single_file(diff)
        assert "test.py" in result
        assert "modified" in result
        assert "+5" in result
        assert "-2" in result
        assert "```diff" in result

    def test_format_single_deleted(self):
        diff = self._make_diff(status="removed", patch="")
        result = _format_single_file(diff)
        assert "*File deleted*" in result

    def test_format_single_renamed(self):
        diff = FileDiff(
            "new.py", "renamed", 0, 0, "", previous_filename="old.py"
        )
        result = _format_single_file(diff)
        assert "Renamed from: old.py" in result

    def test_format_empty_diffs(self):
        result = format_diff_for_llm([])
        assert "No reviewable" in result

    def test_format_multiple_files(self):
        diffs = [
            self._make_diff("a.py", "modified"),
            self._make_diff("b.py", "added"),
        ]
        result = format_diff_for_llm(diffs)
        assert "a.py" in result
        assert "b.py" in result
        assert "---" in result  # separator

    def test_format_priority_order(self):
        diffs = [
            self._make_diff("removed.py", "removed"),
            self._make_diff("added.py", "added"),
            self._make_diff("modified.py", "modified"),
        ]
        result = format_diff_for_llm(diffs)
        # modified should appear before added, added before removed
        mod_pos = result.index("modified.py")
        add_pos = result.index("added.py")
        rem_pos = result.index("removed.py")
        assert mod_pos < add_pos < rem_pos

    def test_truncation(self):
        # Create diffs that exceed char limit
        diffs = [
            self._make_diff(f"file{i}.py", patch="x" * 500)
            for i in range(20)
        ]
        result = format_diff_for_llm(diffs, max_chars=2000)
        assert "truncated" in result

    def test_summary(self):
        diffs = [
            self._make_diff("a.py", additions=10, deletions=3),
            self._make_diff("b.py", additions=5, deletions=1),
        ]
        summary = format_diff_summary(diffs)
        assert summary["total_files"] == 2
        assert summary["total_additions"] == 15
        assert summary["total_deletions"] == 4
        assert len(summary["files"]) == 2


# ---------------------------------------------------------------------------
# GitHubClient (mocked)
# ---------------------------------------------------------------------------

class TestGitHubClient:
    """Test GitHubClient with mocked PyGitHub responses."""

    def _mock_github_file(self, filename, status="modified",
                          additions=5, deletions=2,
                          patch="+new\n-old",
                          previous_filename=None):
        """Create a mock PyGitHub File object."""
        f = MagicMock()
        f.filename = filename
        f.status = status
        f.additions = additions
        f.deletions = deletions
        f.patch = patch
        f.previous_filename = previous_filename
        return f

    @patch("app.github.client.Github")
    def test_get_pr_diff_basic(self, MockGithub):
        mock_instance = MockGithub.return_value
        mock_repo = MagicMock()
        mock_pr = MagicMock()

        mock_files = [
            self._mock_github_file("app/views.py"),
            self._mock_github_file("app/models.py", status="added", deletions=0),
        ]
        mock_pr.get_files.return_value = mock_files
        mock_repo.get_pull.return_value = mock_pr
        mock_instance.get_repo.return_value = mock_repo

        client = GitHubClient(token="fake-token")
        diffs = client.get_pr_diff("owner", "repo", 1)

        assert len(diffs) == 2
        assert diffs[0].filename == "app/views.py"
        assert diffs[1].status == "added"

    @patch("app.github.client.Github")
    def test_filters_lock_files(self, MockGithub):
        mock_instance = MockGithub.return_value
        mock_repo = MagicMock()
        mock_pr = MagicMock()

        mock_files = [
            self._mock_github_file("app/views.py"),
            self._mock_github_file("package-lock.json", additions=5000),
            self._mock_github_file("yarn.lock", additions=3000),
        ]
        mock_pr.get_files.return_value = mock_files
        mock_repo.get_pull.return_value = mock_pr
        mock_instance.get_repo.return_value = mock_repo

        client = GitHubClient(token="fake-token")
        diffs = client.get_pr_diff("owner", "repo", 1)

        assert len(diffs) == 1
        assert diffs[0].filename == "app/views.py"

    @patch("app.github.client.Github")
    def test_filters_binary_files(self, MockGithub):
        mock_instance = MockGithub.return_value
        mock_repo = MagicMock()
        mock_pr = MagicMock()

        mock_files = [
            self._mock_github_file("app/views.py"),
            self._mock_github_file("image.png", patch=None),  # binary = no patch
        ]
        mock_pr.get_files.return_value = mock_files
        mock_repo.get_pull.return_value = mock_pr
        mock_instance.get_repo.return_value = mock_repo

        client = GitHubClient(token="fake-token")
        diffs = client.get_pr_diff("owner", "repo", 1)

        assert len(diffs) == 1

    @patch("app.github.client.Github")
    def test_max_files_cap(self, MockGithub):
        mock_instance = MockGithub.return_value
        mock_repo = MagicMock()
        mock_pr = MagicMock()

        # Create 60 files, cap at 50
        mock_files = [
            self._mock_github_file(f"file{i}.py") for i in range(60)
        ]
        mock_pr.get_files.return_value = mock_files
        mock_repo.get_pull.return_value = mock_pr
        mock_instance.get_repo.return_value = mock_repo

        client = GitHubClient(token="fake-token")
        diffs = client.get_pr_diff("owner", "repo", 1, max_files=50)

        assert len(diffs) <= 50

    @patch("app.github.client.Github")
    def test_empty_pr(self, MockGithub):
        mock_instance = MockGithub.return_value
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.get_files.return_value = []
        mock_repo.get_pull.return_value = mock_pr
        mock_instance.get_repo.return_value = mock_repo

        client = GitHubClient(token="fake-token")
        diffs = client.get_pr_diff("owner", "repo", 1)

        assert diffs == []

    def test_no_token_raises(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": ""}):
            with pytest.raises(ValueError, match="GITHUB_TOKEN"):
                GitHubClient(token="")
