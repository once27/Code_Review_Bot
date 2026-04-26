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
    threshold: str | None = None,
) -> list[ReviewComment]:
    """
    Deduplicate, sort, cap, and threshold-filter review comments.

    Deduplication: If multiple agents flag the same (file, line), keep
    the one with the highest severity. If same severity, merge messages.

    Threshold filtering: Comments below the configured severity threshold
    are dropped. E.g. threshold='warning' drops all 'suggestion' comments.

    Args:
        all_comments: Flat list of comments from all agents.
        max_comments: Max comments to return. Defaults to env MAX_COMMENTS_PER_PR.
        threshold:    Min severity to keep. Defaults to env REVIEW_THRESHOLD.

    Returns:
        Deduplicated, sorted, capped, filtered list of ReviewComment.
    """
    if max_comments is None:
        max_comments = int(os.getenv("MAX_COMMENTS_PER_PR", "20"))

    if threshold is None:
        threshold = os.getenv("REVIEW_THRESHOLD", "suggestion").lower().strip()

    if not all_comments:
        return []

    logger.info("Aggregating %d raw comments from all agents", len(all_comments))

    # Filter by threshold
    threshold_priority = _SEVERITY_PRIORITY.get(threshold, 2)
    filtered = [
        c for c in all_comments
        if _SEVERITY_PRIORITY.get(c.severity, 9) <= threshold_priority
    ]

    if len(filtered) < len(all_comments):
        logger.info(
            "Threshold '%s' filtered out %d comments",
            threshold, len(all_comments) - len(filtered),
        )

    if not filtered:
        return []

    # Group by (file, line)
    grouped: dict[tuple[str, int], list[ReviewComment]] = {}
    for comment in filtered:
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
        "Aggregation complete: %d comments (from %d raw, threshold=%s)",
        len(deduped), len(all_comments), threshold,
    )
    return deduped

