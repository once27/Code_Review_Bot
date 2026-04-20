"""
Diff Formatter — Prepare PR diffs for LLM consumption.

Converts a list of ``FileDiff`` objects into a clean, structured string
that language models can parse efficiently. Includes truncation safety
to stay within token budgets.

Usage:
    from app.github.diff_formatter import format_diff_for_llm, format_diff_summary
    formatted = format_diff_for_llm(diffs, max_chars=10000)
    summary   = format_diff_summary(diffs)
"""

import logging

from app.github.client import FileDiff

logger = logging.getLogger("app.github.diff_formatter")

# ---------------------------------------------------------------------------
# Status Emoji Mapping
# ---------------------------------------------------------------------------

_STATUS_EMOJI: dict[str, str] = {
    "added": "🟢",
    "modified": "🔵",
    "removed": "🔴",
    "renamed": "🟡",
    "copied": "⚪",
}


def _format_single_file(diff: FileDiff) -> str:
    """
    Format a single FileDiff into a readable block for the LLM.

    Output:
        ## File: app/auth/views.py (modified, +15 -3)

        ```diff
        <patch content>
        ```
    """
    emoji = _STATUS_EMOJI.get(diff.status, "⚪")
    header = (
        f"## {emoji} File: {diff.filename} "
        f"({diff.status}, +{diff.additions} -{diff.deletions})"
    )

    if diff.previous_filename:
        header += f"\n   Renamed from: {diff.previous_filename}"

    if diff.status == "removed":
        return f"{header}\n\n*File deleted*"

    if not diff.patch:
        return f"{header}\n\n*No patch available (binary or empty)*"

    return f"{header}\n\n```diff\n{diff.patch}\n```"


def format_diff_for_llm(
    diffs: list[FileDiff],
    *,
    max_chars: int = 10_000,
) -> str:
    """
    Format all file diffs into a single LLM-ready string.

    Files are ordered by significance: modified first, then added, then
    renamed/copied, then removed. If the total output exceeds ``max_chars``,
    lower-priority files are truncated with a warning.

    Args:
        diffs:     List of FileDiff objects from GitHubClient.
        max_chars: Maximum characters in the output. Prevents token overflow.

    Returns:
        Formatted diff string ready for LLM agent consumption.
    """
    if not diffs:
        return "No reviewable file changes in this PR."

    # Sort by priority: modified > added > renamed > removed
    priority = {"modified": 0, "added": 1, "renamed": 2, "copied": 3, "removed": 4}
    sorted_diffs = sorted(diffs, key=lambda d: priority.get(d.status, 5))

    sections: list[str] = []
    total_chars = 0
    truncated_count = 0

    for diff in sorted_diffs:
        section = _format_single_file(diff)
        section_len = len(section)

        if total_chars + section_len > max_chars and sections:
            truncated_count += 1
            continue

        sections.append(section)
        total_chars += section_len

    output = "\n\n---\n\n".join(sections)

    if truncated_count > 0:
        output += (
            f"\n\n---\n\n⚠️ **{truncated_count} file(s) truncated** "
            f"to stay within the {max_chars} character limit."
        )
        logger.warning(
            "Diff truncated: %d files dropped (limit: %d chars)",
            truncated_count, max_chars,
        )

    return output


def format_diff_summary(diffs: list[FileDiff]) -> dict:
    """
    Generate a summary dict for logging and API responses.

    Returns:
        Dict with keys: total_files, total_additions, total_deletions,
        files (list of {filename, status, additions, deletions}).
    """
    return {
        "total_files": len(diffs),
        "total_additions": sum(d.additions for d in diffs),
        "total_deletions": sum(d.deletions for d in diffs),
        "files": [
            {
                "filename": d.filename,
                "status": d.status,
                "additions": d.additions,
                "deletions": d.deletions,
            }
            for d in diffs
        ],
    }
