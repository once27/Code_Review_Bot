"""
RAG Retriever — Query ChromaDB for relevant codebase context.

Given a diff text, embeds it as a query and retrieves the most similar
code chunks from the indexed repository. Returns a formatted context
string ready for injection into agent prompts.

Usage:
    from app.rag.retriever import retrieve_context
    context = retrieve_context(diff_text, "once27/test-review-bot", top_k=5)
"""

import logging
import os

import chromadb
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("app.rag.retriever")

CHROMA_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")

# Singleton model reference (shared with indexer if both loaded)
_embed_model: SentenceTransformer | None = None


def _get_embed_model() -> SentenceTransformer:
    """Lazy-load embedding model (singleton)."""
    global _embed_model
    if _embed_model is None:
        logger.info("Loading embedding model: %s", EMBED_MODEL)
        _embed_model = SentenceTransformer(EMBED_MODEL)
    return _embed_model


def _get_chroma_collection(repo_key: str) -> chromadb.Collection | None:
    """Get ChromaDB collection for a repo. Returns None if not found."""
    try:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        # Sanitize: only alphanumeric, underscores, hyphens allowed
        import re
        collection_name = "repo_" + re.sub(r"[^a-zA-Z0-9_-]", "_", repo_key)
        collection_name = collection_name[:63]
        collection = client.get_collection(name=collection_name)
        return collection
    except Exception:
        logger.debug("No ChromaDB collection found for %s", repo_key)
        return None


def retrieve_context(
    diff_text: str,
    repo_key: str,
    top_k: int = 5,
    branch: str | None = None,
) -> str | None:
    """
    Retrieve relevant codebase context for a given diff.

    Args:
        diff_text: Formatted diff string to use as query.
        repo_key:  Repository key (e.g., "once27/test-review-bot").
        top_k:     Number of similar chunks to retrieve.
        branch:    Optional branch to search context from.

    Returns:
        Formatted context string, or None if no context available.
    """
    # Try branch-specific collection first
    collection = None
    if branch:
        branch_repo_key = f"{repo_key}:{branch}"
        collection = _get_chroma_collection(branch_repo_key)
        if collection:
            logger.info("Using branch-specific RAG index: %s", branch_repo_key)

    # Fallback to default repo collection
    if not collection:
        collection = _get_chroma_collection(repo_key)

    if collection is None:
        logger.info("No RAG index found for %s — skipping context retrieval", repo_key)
        return None

    count = collection.count()
    if count == 0:
        logger.info("RAG index for %s is empty — skipping", repo_key)
        return None

    # Truncate diff to avoid embedding very long texts
    query_text = diff_text[:2000]

    try:
        model = _get_embed_model()
        query_embedding = model.encode([query_text]).tolist()

        results = collection.query(
            query_embeddings=query_embedding,
            n_results=min(top_k, count),
            include=["documents", "metadatas", "distances"],
        )

        if not results["documents"] or not results["documents"][0]:
            logger.info("No relevant context found for %s", repo_key)
            return None

        # Format context for agent injection
        context_parts = []
        seen_files = set()

        for doc, metadata, distance in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            filename = metadata.get("filename", "unknown")
            chunk_idx = metadata.get("chunk_index", 0)
            similarity = 1 - distance  # cosine distance → similarity

            # Skip low-relevance chunks
            if similarity < 0.3:
                continue

            # Track unique files for logging
            seen_files.add(filename)

            context_parts.append(
                f"### {filename} (chunk {chunk_idx}, similarity: {similarity:.2f})\n"
                f"```\n{doc[:500]}\n```"
            )

        if not context_parts:
            logger.info("All retrieved chunks below relevance threshold")
            return None

        context = (
            "## Relevant Existing Code from This Repository\n"
            "Use this context to ensure consistency with existing patterns.\n\n"
            + "\n\n".join(context_parts)
        )

        logger.info(
            "RAG context retrieved — %d chunks from %d files for %s",
            len(context_parts), len(seen_files), repo_key,
        )
        return context

    except Exception as exc:
        logger.error("RAG retrieval failed for %s: %s", repo_key, exc)
        return None
