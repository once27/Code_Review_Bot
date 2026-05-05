"""
Celery Application instance for running background tasks.

Uses Redis as the message broker and result backend.
"""

import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "code_review_bot",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.rag.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
