"""
Agent Memory — Suppressed pattern detection for the feedback loop.

Queries dismissed feedback patterns and returns a list of patterns
that agents should avoid flagging in future reviews. A pattern is
suppressed when it has ≥3 dismissals and 0 acceptances in the last
30 days.

Usage:
    from app.agents.memory import get_suppressed_patterns
    suppressed = get_suppressed_patterns("once27", "test-review-bot")
"""

import datetime
import logging

from sqlalchemy import func

from app.db.session import get_session
from app.models.review import Review, ReviewComment, Feedback

logger = logging.getLogger("app.agents.memory")

DISMISSAL_THRESHOLD = 3  # Minimum dismissals to suppress
LOOKBACK_DAYS = 30


def get_suppressed_patterns(repo_owner: str, repo_name: str) -> list[dict]:
    """
    Find review patterns that developers consistently dismiss.

    A pattern is suppressed when:
    - Same agent_type + similar message has ≥3 dismissals
    - Zero acceptances in the same period

    Args:
        repo_owner: Repository owner.
        repo_name:  Repository name.

    Returns:
        List of dicts: [{"agent_type": "...", "pattern": "..."}]
    """
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=LOOKBACK_DAYS)

    try:
        session = get_session()

        # Get all dismissed comments with their agent_type and message
        dismissed = (
            session.query(
                ReviewComment.agent_type,
                ReviewComment.message,
                ReviewComment.id,
            )
            .join(Feedback, Feedback.comment_id == ReviewComment.id)
            .join(Review, ReviewComment.review_id == Review.id)
            .filter(
                Review.repo_owner == repo_owner,
                Review.repo_name == repo_name,
                Feedback.action == "dismissed",
                Feedback.created_at >= cutoff,
            )
            .all()
        )

        # Get all accepted comment IDs (to exclude from suppression)
        accepted_ids = set(
            row[0] for row in
            session.query(Feedback.comment_id)
            .join(ReviewComment, Feedback.comment_id == ReviewComment.id)
            .join(Review, ReviewComment.review_id == Review.id)
            .filter(
                Review.repo_owner == repo_owner,
                Review.repo_name == repo_name,
                Feedback.action == "accepted",
                Feedback.created_at >= cutoff,
            )
            .all()
        )

        session.close()

        if not dismissed:
            return []

        # Group by agent_type and extract pattern keywords
        # A "pattern" is the first 80 chars of the message (normalized)
        pattern_counts = {}
        for agent_type, message, comment_id in dismissed:
            # Skip if this comment was also accepted
            if comment_id in accepted_ids:
                continue

            # Extract pattern: first 80 chars, lowercased, stripped
            pattern_key = (agent_type, message[:80].lower().strip())
            pattern_counts[pattern_key] = pattern_counts.get(pattern_key, 0) + 1

        # Filter: only patterns with ≥ threshold dismissals
        suppressed = []
        for (agent_type, pattern), count in pattern_counts.items():
            if count >= DISMISSAL_THRESHOLD:
                suppressed.append({
                    "agent_type": agent_type,
                    "pattern": pattern,
                    "dismissals": count,
                })

        if suppressed:
            logger.info(
                "Found %d suppressed patterns for %s/%s",
                len(suppressed), repo_owner, repo_name,
            )

        return suppressed

    except Exception as exc:
        logger.error("Failed to query suppressed patterns: %s", exc)
        return []


def format_suppressed_for_prompt(suppressed: list[dict]) -> str:
    """
    Format suppressed patterns into a string for agent prompt injection.

    Args:
        suppressed: List from get_suppressed_patterns().

    Returns:
        Formatted string, or empty string if no suppressions.
    """
    if not suppressed:
        return ""

    lines = ["## Suppressed Patterns (Team has dismissed these repeatedly)",
             "Do NOT flag the following patterns:\n"]

    for item in suppressed:
        lines.append(f"- [{item['agent_type']}] {item['pattern']}")

    return "\n".join(lines)
