"""
CRUD operations for review persistence.

Provides save_review() to store a completed review and its comments
in the database after posting to GitHub.
"""

import logging

from app.db.session import get_session
from app.models.review import Review, ReviewComment as DBReviewComment
from app.agents.base_agent import ReviewComment as AgentComment

logger = logging.getLogger("app.db.crud")


def save_review(
    *,
    repo_owner: str,
    repo_name: str,
    pr_number: int,
    pr_author: str | None,
    commit_sha: str,
    event_type: str,
    comments: list[AgentComment],
    agents_used: list[str] | None = None,
    threshold: str | None = None,
    pipeline_duration_ms: int | None = None,
) -> int | None:
    """
    Persist a review and its comments to the database.

    Args:
        repo_owner:          Repository owner.
        repo_name:           Repository name.
        pr_number:           Pull request number.
        pr_author:           PR author username.
        commit_sha:          Commit SHA reviewed.
        event_type:          GitHub review event (COMMENT/REQUEST_CHANGES).
        comments:            List of AgentComment (ReviewComment dataclass).
        agents_used:         Which agents ran.
        threshold:           Severity threshold used.
        pipeline_duration_ms: How long the pipeline took.

    Returns:
        Review ID if saved, None if failed.
    """
    # Count severities
    counts = {"critical": 0, "warning": 0, "suggestion": 0}
    for c in comments:
        counts[c.severity] = counts.get(c.severity, 0) + 1

    try:
        session = get_session()

        review = Review(
            repo_owner=repo_owner,
            repo_name=repo_name,
            pr_number=pr_number,
            pr_author=pr_author,
            commit_sha=commit_sha,
            event_type=event_type,
            total_comments=len(comments),
            critical_count=counts["critical"],
            warning_count=counts["warning"],
            suggestion_count=counts["suggestion"],
            agents_used=",".join(agents_used) if agents_used else None,
            threshold=threshold,
            pipeline_duration_ms=pipeline_duration_ms,
        )

        # Add comments
        for c in comments:
            db_comment = DBReviewComment(
                file=c.file,
                line=c.line,
                severity=c.severity,
                agent_type=c.agent_type,
                message=c.message,
            )
            review.comments.append(db_comment)

        session.add(review)
        session.commit()

        review_id = review.id
        session.close()

        logger.info(
            "Review #%d saved to DB (PR #%d, %d comments)",
            review_id, pr_number, len(comments),
        )
        return review_id

    except Exception as exc:
        logger.error("Failed to save review to DB: %s", exc)
        return None
