"""
Review Aggregator — Deduplicate, merge, and sort review comments.

After all agents run in parallel, the aggregator:
1. Deduplicates: if two agents flag the same file+line, keep higher severity.
2. Sorts: critical first, then warning, then suggestion.
3. Caps: limits total comments per PR (configurable via MAX_COMMENTS_PER_PR).
"""

import logging
import os

from app.agents.base_agent import ReviewComment

logger = logging.getLogger("app.agents.aggregator")

# Priority map: lower = higher priority
_SEVERITY_PRIORITY = {
    "critical": 0,
    "warning": 1,
    "suggestion": 2,
}


def aggregate_comments(
    all_comments: list[ReviewComment],
    *,
    max_comments: int | None = None,
) -> list[ReviewComment]:
    """
    Deduplicate, sort, and cap review comments from multiple agents.

    Deduplication: If multiple agents flag the same (file, line), keep
    the one with the highest severity. If same severity, merge messages.

    Args:
        all_comments: Flat list of comments from all agents.
        max_comments: Max comments to return. Defaults to env MAX_COMMENTS_PER_PR.

    Returns:
        Deduplicated, sorted, capped list of ReviewComment.
    """
    if max_comments is None:
        max_comments = int(os.getenv("MAX_COMMENTS_PER_PR", "20"))

    if not all_comments:
        return []

    logger.info("Aggregating %d raw comments from all agents", len(all_comments))

    # Group by (file, line)
    grouped: dict[tuple[str, int], list[ReviewComment]] = {}
    for comment in all_comments:
        key = (comment.file, comment.line)
        grouped.setdefault(key, []).append(comment)

    # Deduplicate: pick highest severity per (file, line), merge messages
    deduped: list[ReviewComment] = []
    for (file, line), comments in grouped.items():
        # Sort by severity priority (critical first)
        comments.sort(key=lambda c: _SEVERITY_PRIORITY.get(c.severity, 9))

        best = comments[0]

        # If multiple agents flagged same line, merge unique messages
        if len(comments) > 1:
            seen_messages = {best.message}
            extra_parts = []
            for c in comments[1:]:
                if c.message not in seen_messages:
                    seen_messages.add(c.message)
                    extra_parts.append(f"[{c.agent_type}] {c.message}")

            if extra_parts:
                merged_msg = (
                    f"{best.message}\n\n"
                    + "**Also flagged by:**\n"
                    + "\n".join(f"- {p}" for p in extra_parts)
                )
            else:
                merged_msg = best.message

            best = ReviewComment(
                file=file,
                line=line,
                severity=best.severity,
                message=merged_msg,
                agent_type=best.agent_type,
            )

        deduped.append(best)

    # Sort: critical → warning → suggestion
    deduped.sort(key=lambda c: _SEVERITY_PRIORITY.get(c.severity, 9))

    # Cap
    if len(deduped) > max_comments:
        logger.warning(
            "Capping comments from %d to %d", len(deduped), max_comments
        )
        deduped = deduped[:max_comments]

    logger.info(
        "Aggregation complete: %d comments (from %d raw)",
        len(deduped), len(all_comments),
    )
    return deduped
