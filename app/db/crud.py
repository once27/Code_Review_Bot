"""
CRUD operations for review persistence and feedback.

Provides save_review() to store a completed review and its comments
in the database after posting to GitHub, plus feedback operations
for the developer learning loop.
"""

import datetime
import logging

from sqlalchemy import func

from app.db.session import get_session
from app.models.review import Review, ReviewComment as DBReviewComment, Feedback
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


def save_feedback(
    *,
    comment_id: int,
    developer: str,
    action: str,
) -> int | None:
    """
    Save developer feedback on a review comment.

    Args:
        comment_id: ID of the ReviewComment being acted on.
        developer:  GitHub username of the developer.
        action:     "accepted" or "dismissed".

    Returns:
        Feedback ID if saved, None if failed.
    """
    if action not in ("accepted", "dismissed"):
        logger.error("Invalid feedback action: %s", action)
        return None

    try:
        session = get_session()

        # Verify comment exists
        comment = session.get(DBReviewComment, comment_id)
        if not comment:
            logger.warning("Feedback for non-existent comment #%d", comment_id)
            session.close()
            return None

        feedback = Feedback(
            comment_id=comment_id,
            developer=developer,
            action=action,
        )
        session.add(feedback)
        session.commit()

        feedback_id = feedback.id
        session.close()

        logger.info(
            "Feedback #%d saved: comment=%d action=%s by=%s",
            feedback_id, comment_id, action, developer,
        )
        return feedback_id

    except Exception as exc:
        logger.error("Failed to save feedback: %s", exc)
        return None


def get_feedback_stats(repo_owner: str, repo_name: str) -> dict:
    """
    Get acceptance rate per agent type for a repo.

    Returns:
        Dict with per-agent stats and overall totals.
    """
    try:
        session = get_session()

        # Join Feedback → ReviewComment → Review to filter by repo
        results = (
            session.query(
                DBReviewComment.agent_type,
                Feedback.action,
                func.count(Feedback.id).label("count"),
            )
            .join(DBReviewComment, Feedback.comment_id == DBReviewComment.id)
            .join(Review, DBReviewComment.review_id == Review.id)
            .filter(
                Review.repo_owner == repo_owner,
                Review.repo_name == repo_name,
            )
            .group_by(DBReviewComment.agent_type, Feedback.action)
            .all()
        )

        session.close()

        # Build per-agent stats
        agents = {}
        for agent_type, action, count in results:
            if agent_type not in agents:
                agents[agent_type] = {"accepted": 0, "dismissed": 0}
            agents[agent_type][action] = count

        # Calculate acceptance rates
        stats = {}
        total_accepted = 0
        total_dismissed = 0
        for agent, counts in agents.items():
            accepted = counts["accepted"]
            dismissed = counts["dismissed"]
            total = accepted + dismissed
            stats[agent] = {
                "accepted": accepted,
                "dismissed": dismissed,
                "total": total,
                "acceptance_rate": round(accepted / total, 2) if total > 0 else 0,
            }
            total_accepted += accepted
            total_dismissed += dismissed

        grand_total = total_accepted + total_dismissed
        return {
            "repo": f"{repo_owner}/{repo_name}",
            "per_agent": stats,
            "overall": {
                "accepted": total_accepted,
                "dismissed": total_dismissed,
                "total": grand_total,
                "acceptance_rate": round(total_accepted / grand_total, 2) if grand_total > 0 else 0,
            },
        }

    except Exception as exc:
        logger.error("Failed to get feedback stats: %s", exc)
        return {"error": str(exc)}


def get_health_score(repo_owner: str, repo_name: str) -> dict:
    """
    Calculate Review Health Score for a repo.

    Score = (accepted × weight) / total_non_dismissed over last 30 days.
    Weights: critical=3, warning=2, suggestion=1.
    """
    SEVERITY_WEIGHTS = {"critical": 3, "warning": 2, "suggestion": 1}
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=30)

    try:
        session = get_session()

        # Get all feedback with comment severity info from last 30 days
        results = (
            session.query(
                Feedback.action,
                Feedback.developer,
                DBReviewComment.severity,
            )
            .join(DBReviewComment, Feedback.comment_id == DBReviewComment.id)
            .join(Review, DBReviewComment.review_id == Review.id)
            .filter(
                Review.repo_owner == repo_owner,
                Review.repo_name == repo_name,
                Feedback.created_at >= cutoff,
            )
            .all()
        )

        session.close()

        if not results:
            return {
                "repo": f"{repo_owner}/{repo_name}",
                "period_days": 30,
                "score": 0,
                "total_feedback": 0,
                "per_developer": {},
            }

        # Calculate per-developer scores
        dev_stats = {}
        for action, developer, severity in results:
            if developer not in dev_stats:
                dev_stats[developer] = {"weighted_accepted": 0, "total_weight": 0}

            weight = SEVERITY_WEIGHTS.get(severity, 1)
            dev_stats[developer]["total_weight"] += weight
            if action == "accepted":
                dev_stats[developer]["weighted_accepted"] += weight

        # Build per-developer scores
        per_dev = {}
        total_weighted = 0
        total_accepted_weighted = 0
        for dev, data in dev_stats.items():
            score = round(data["weighted_accepted"] / data["total_weight"], 2) if data["total_weight"] > 0 else 0
            per_dev[dev] = {"score": score, "total_weight": data["total_weight"]}
            total_weighted += data["total_weight"]
            total_accepted_weighted += data["weighted_accepted"]

        overall_score = round(total_accepted_weighted / total_weighted, 2) if total_weighted > 0 else 0

        return {
            "repo": f"{repo_owner}/{repo_name}",
            "period_days": 30,
            "score": overall_score,
            "total_feedback": len(results),
            "per_developer": per_dev,
        }

    except Exception as exc:
        logger.error("Failed to calculate health score: %s", exc)
        return {"error": str(exc)}
