"""
Multi-Agent Review Pipeline — Parallel execution of specialist agents.

Replaces the single GeneralReviewAgent from Sprint 4 with four
specialized agents running concurrently via asyncio.gather.

Usage:
    from app.agents.pipeline import run_review_pipeline
    comments = await run_review_pipeline(formatted_diff)
"""

import asyncio
import logging
import time

from app.agents.base_agent import ReviewComment
from app.agents.security_agent import SecurityAgent
from app.agents.performance_agent import PerformanceAgent
from app.agents.logic_agent import LogicAgent
from app.agents.style_agent import StyleAgent
from app.agents.aggregator import aggregate_comments

logger = logging.getLogger("app.agents.pipeline")


async def run_review_pipeline(
    diff_text: str,
    *,
    max_comments: int | None = None,
) -> list[ReviewComment]:
    """
    Run all specialist agents in parallel and aggregate results.

    Args:
        diff_text:    Formatted diff string from diff_formatter.
        max_comments: Optional cap on total comments returned.

    Returns:
        Deduplicated, sorted list of ReviewComment objects.
    """
    if not diff_text or "No reviewable" in diff_text:
        logger.info("No diff to review, skipping pipeline")
        return []

    # Initialize all agents
    agents = [
        SecurityAgent(),
        PerformanceAgent(),
        LogicAgent(),
        StyleAgent(),
    ]

    logger.info("Starting multi-agent pipeline (%d agents)", len(agents))
    start = time.monotonic()

    # Run all agents in parallel
    results = await asyncio.gather(
        *(agent.review(diff_text) for agent in agents),
        return_exceptions=True,
    )

    elapsed = time.monotonic() - start

    # Collect comments, log any agent failures
    all_comments: list[ReviewComment] = []
    for agent, result in zip(agents, results):
        if isinstance(result, Exception):
            logger.error(
                "%s agent failed: %s", agent.agent_type, result
            )
            continue
        logger.info(
            "%s agent returned %d comments", agent.agent_type, len(result)
        )
        all_comments.extend(result)

    logger.info(
        "Pipeline completed in %.2fs — %d raw comments from %d agents",
        elapsed, len(all_comments), len(agents),
    )

    # Aggregate: deduplicate, sort, cap
    final = aggregate_comments(all_comments, max_comments=max_comments)

    return final
