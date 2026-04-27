"""
Review models — SQLAlchemy ORM for persisting review history.

Tables:
    reviews:        One row per PR review (metadata + summary).
    review_comments: Individual comments within a review.
"""

import datetime
import logging

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship

logger = logging.getLogger("app.models.review")


class Base(DeclarativeBase):
    """Shared base class for all ORM models."""
    pass


class Review(Base):
    """A single PR review event."""

    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # GitHub identifiers
    repo_owner = Column(String(255), nullable=False)
    repo_name = Column(String(255), nullable=False)
    pr_number = Column(Integer, nullable=False)
    pr_author = Column(String(255), nullable=True)
    commit_sha = Column(String(40), nullable=False)

    # Review metadata
    event_type = Column(String(20), nullable=False, default="COMMENT")
    total_comments = Column(Integer, nullable=False, default=0)
    critical_count = Column(Integer, nullable=False, default=0)
    warning_count = Column(Integer, nullable=False, default=0)
    suggestion_count = Column(Integer, nullable=False, default=0)

    # Agent config used
    agents_used = Column(String(255), nullable=True)
    threshold = Column(String(20), nullable=True)

    # Processing stats
    pipeline_duration_ms = Column(Integer, nullable=True)

    # Timestamps
    created_at = Column(
        DateTime, nullable=False,
        default=datetime.datetime.utcnow,
    )

    # Relationships
    comments = relationship(
        "ReviewComment",
        back_populates="review",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_reviews_repo", "repo_owner", "repo_name"),
        Index("ix_reviews_pr", "repo_owner", "repo_name", "pr_number"),
    )

    def __repr__(self):
        return (
            f"<Review #{self.id} PR#{self.pr_number} "
            f"on {self.repo_owner}/{self.repo_name}>"
        )


class ReviewComment(Base):
    """An individual comment within a review."""

    __tablename__ = "review_comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=False)

    # Comment data
    file = Column(String(500), nullable=False)
    line = Column(Integer, nullable=False)
    severity = Column(String(20), nullable=False)
    agent_type = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)

    # Timestamps
    created_at = Column(
        DateTime, nullable=False,
        default=datetime.datetime.utcnow,
    )

    # Relationships
    review = relationship("Review", back_populates="comments")

    __table_args__ = (
        Index("ix_comments_severity", "severity"),
        Index("ix_comments_file", "file"),
    )

    def __repr__(self):
        return (
            f"<ReviewComment [{self.severity}] {self.file}:{self.line}>"
        )
