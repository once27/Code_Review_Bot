"""
RAG Indexer — Clone and index a repository into ChromaDB.

Clones repo via `git clone --depth 1`, walks Python files, chunks them
into overlapping segments, embeds via SentenceTransformers, and stores
in a persistent ChromaDB collection.

Usage:
    from app.rag.indexer import index_repository
    stats = index_repository("once27", "test-review-bot")
"""

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("app.rag.indexer")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHROMA_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

# File extensions to index
INDEXABLE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".rb"}

# Directories to always skip
SKIP_DIRS = {
    "__pycache__", ".git", ".github", "venv", "env", ".venv",
    "node_modules", ".tox", ".mypy_cache", ".pytest_cache",
    "dist", "build", ".eggs", "*.egg-info",
}

# Maximum file size to index (skip large generated files)
MAX_FILE_SIZE = 50_000  # 50KB

# Singleton model (loaded once)
_embed_model: SentenceTransformer | None = None


def _get_embed_model() -> SentenceTransformer:
    """Lazy-load embedding model (singleton)."""
    global _embed_model
    if _embed_model is None:
        logger.info("Loading embedding model: %s", EMBED_MODEL)
        _embed_model = SentenceTransformer(EMBED_MODEL)
        logger.info("Embedding model loaded")
    return _embed_model


def _get_chroma_collection(repo_key: str) -> chromadb.Collection:
    """Get or create a ChromaDB collection for a repo."""
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    # Sanitize: only alphanumeric, underscores, hyphens allowed
    import re
    collection_name = "repo_" + re.sub(r"[^a-zA-Z0-9_-]", "_", repo_key)
    # Truncate to ChromaDB's 63-char limit
    collection_name = collection_name[:63]
    return client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def _should_skip_dir(dirname: str) -> bool:
    """Check if directory should be skipped."""
    return dirname in SKIP_DIRS or dirname.startswith(".")


def _clone_repo(owner: str, repo_name: str, target_dir: str, branch: str | None = None) -> bool:
    """Shallow clone a repo. Returns True on success."""
    github_token = os.getenv("GITHUB_TOKEN", "")
    if github_token:
        url = f"https://x-access-token:{github_token}@github.com/{owner}/{repo_name}.git"
    else:
        url = f"https://github.com/{owner}/{repo_name}.git"

    command = ["git", "clone", "--depth", "1"]
    if branch:
        command.extend(["-b", branch])
    command.extend([url, target_dir])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error("Git clone failed: %s", result.stderr)
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("Git clone timed out for %s/%s (branch: %s)", owner, repo_name, branch)
        return False
    except FileNotFoundError:
        logger.error("git not found on system. Install git to use RAG indexing.")
        return False


def index_repository(owner: str, repo_name: str, branch: str | None = None) -> dict:
    """
    Clone and index a repository into ChromaDB.

    Args:
        owner:     Repository owner (e.g., "once27").
        repo_name: Repository name (e.g., "test-review-bot").
        branch:    Optional branch to index (defaults to repo default branch).

    Returns:
        Dict with indexing stats: files_indexed, chunks_created, duration_s.
    """
    repo_key = f"{owner}/{repo_name}"
    if branch:
        repo_key = f"{repo_key}:{branch}"

    logger.info("Starting indexing for %s", repo_key)
    start = time.monotonic()

    # Clone to temp directory
    tmp_dir = tempfile.mkdtemp(prefix="codereview_rag_")
    try:
        if not _clone_repo(owner, repo_name, tmp_dir, branch):
            return {"error": f"Failed to clone {repo_key}", "files_indexed": 0}

        # Get collection (clear old data for re-index)
        collection = _get_chroma_collection(repo_key)

        # Delete existing documents for clean re-index
        existing = collection.count()
        if existing > 0:
            logger.info("Clearing %d existing chunks for %s", existing, repo_key)
            # Get all IDs and delete
            all_ids = collection.get()["ids"]
            if all_ids:
                collection.delete(ids=all_ids)

        # Walk and index files
        model = _get_embed_model()
        files_indexed = 0
        all_chunks = []
        all_ids = []
        all_metadatas = []

        repo_path = Path(tmp_dir)
        for filepath in repo_path.rglob("*"):
            # Skip directories
            if filepath.is_dir():
                continue

            # Skip non-indexable extensions
            if filepath.suffix not in INDEXABLE_EXTENSIONS:
                continue

            # Skip files in excluded directories
            rel_parts = filepath.relative_to(repo_path).parts
            if any(_should_skip_dir(p) for p in rel_parts[:-1]):
                continue

            # Skip large files
            if filepath.stat().st_size > MAX_FILE_SIZE:
                continue

            # Read and chunk
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            if not content.strip():
                continue

            rel_path = str(filepath.relative_to(repo_path))
            chunks = _chunk_text(content)

            for i, chunk in enumerate(chunks):
                chunk_id = f"{repo_key}::{rel_path}::chunk_{i}"
                all_chunks.append(chunk)
                all_ids.append(chunk_id)
                all_metadatas.append({
                    "repo": repo_key,
                    "filename": rel_path,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                })

            files_indexed += 1

        if not all_chunks:
            logger.warning("No indexable files found in %s", repo_key)
            return {"files_indexed": 0, "chunks_created": 0, "duration_s": 0}

        # Batch embed and upsert
        logger.info("Embedding %d chunks from %d files...", len(all_chunks), files_indexed)
        embeddings = model.encode(all_chunks, show_progress_bar=False).tolist()

        # ChromaDB batch limit is 5000
        batch_size = 5000
        for i in range(0, len(all_chunks), batch_size):
            end = min(i + batch_size, len(all_chunks))
            collection.add(
                ids=all_ids[i:end],
                embeddings=embeddings[i:end],
                documents=all_chunks[i:end],
                metadatas=all_metadatas[i:end],
            )

        elapsed = time.monotonic() - start
        stats = {
            "repo": repo_key,
            "files_indexed": files_indexed,
            "chunks_created": len(all_chunks),
            "duration_s": round(elapsed, 2),
        }
        logger.info(
            "Indexing complete for %s — %d files, %d chunks in %.1fs",
            repo_key, files_indexed, len(all_chunks), elapsed,
        )
        return stats

    finally:
        # Clean up temp directory
        shutil.rmtree(tmp_dir, ignore_errors=True)
