"""
Database Session — SQLAlchemy engine and session factory.

Uses DATABASE_URL from .env. Falls back to SQLite for local dev
if Postgres is not available.

Usage:
    from app.db.session import get_engine, get_session
    engine = get_engine()
    with get_session() as session:
        session.add(review)
        session.commit()
"""

import logging
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger("app.db.session")

_engine = None
_SessionLocal = None


def get_engine():
    """Get or create the SQLAlchemy engine (singleton)."""
    global _engine
    if _engine is not None:
        return _engine

    db_url = os.getenv("DATABASE_URL", "")

    # Fallback to SQLite for dev if no Postgres configured or connection fails
    if not db_url or db_url.startswith("postgresql://user:password@"):
        db_url = "sqlite:///reviews.db"
        logger.info("Using SQLite for local dev: reviews.db")
    else:
        logger.info("Using database: %s", db_url.split("@")[-1] if "@" in db_url else db_url)

    _engine = create_engine(
        db_url,
        echo=False,
        pool_pre_ping=True if not db_url.startswith("sqlite") else False,
    )

    # Enable WAL mode for SQLite (better concurrent reads)
    if db_url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return _engine


def get_session_factory():
    """Get or create the session factory (singleton)."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal


def get_session() -> Session:
    """Create a new database session."""
    factory = get_session_factory()
    return factory()


def init_db():
    """Create all tables. Call once on startup."""
    from app.models.review import Base  # noqa: F811

    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("Database tables created/verified")
