"""
Celery tasks for background processing of RAG operations.
"""

import logging
from app.worker import celery_app
from app.rag.indexer import index_repository

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, name="run_index_repository")
def run_index_repository(self, owner: str, repo_name: str, branch: str | None = None):
    """
    Background task to clone, chunk, and embed a repository into ChromaDB.
    """
    logger.info("Background task started: Indexing %s/%s (branch: %s)", owner, repo_name, branch)
    
    try:
        # Call the existing synchronous indexing logic
        stats = index_repository(owner, repo_name, branch)
        return stats
    except Exception as exc:
        logger.error("Background task failed: %s", exc)
        self.update_state(
            state="FAILURE",
            meta={"exc_type": type(exc).__name__, "exc_message": str(exc)}
        )
        raise exc
