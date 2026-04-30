"""
Multi-Agent Review Pipeline — Parallel execution of specialist agents.

Replaces the single GeneralReviewAgent with four
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

# Map agent_type string → class
_AGENT_MAP = {
    "security": SecurityAgent,
    "performance": PerformanceAgent,
    "logic": LogicAgent,
    "style": StyleAgent,
}


async def run_review_pipeline(
    diff_text: str,
    *,
    max_comments: int | None = None,
    threshold: str | None = None,
    enabled_agents: list[str] | None = None,
    custom_rules: list[str] | None = None,
    codebase_context: str | None = None,
) -> list[ReviewComment]:
    """
    Run specialist agents in parallel and aggregate results.

    Args:
        diff_text:      Formatted diff string from diff_formatter.
        max_comments:      Optional cap on total comments returned.
        threshold:         Min severity to keep (from .codereview.yml).
        enabled_agents:    Which agents to run (from .codereview.yml).
        custom_rules:      Extra rules injected into agent prompts.
        codebase_context:  RAG-retrieved context from repository.

    Returns:
        Deduplicated, sorted list of ReviewComment objects.
    """
    if not diff_text or "No reviewable" in diff_text:
        logger.info("No diff to review, skipping pipeline")
        return []

    # Select agents based on config
    if enabled_agents:
        agent_types = [a for a in enabled_agents if a in _AGENT_MAP]
    else:
        agent_types = list(_AGENT_MAP.keys())

    if not agent_types:
        logger.warning("No valid agents enabled — using all")
        agent_types = list(_AGENT_MAP.keys())

    # Initialize selected agents
    agents = [_AGENT_MAP[t]() for t in agent_types]

    # If custom rules, append them to the diff as extra context
    review_input = diff_text
    if custom_rules:
        rules_block = "\n\n## 📋 Custom Review Rules (from .codereview.yml)\n"
        rules_block += "\n".join(f"- {r}" for r in custom_rules)
        review_input = diff_text + rules_block
        logger.info("Injected %d custom rules into prompt", len(custom_rules))

    logger.info(
        "Starting multi-agent pipeline (%d agents: %s)",
        len(agents), ", ".join(agent_types),
    )
    start = time.monotonic()

    # Log RAG context if present
    if codebase_context:
        logger.info("RAG codebase context injected (%d chars)", len(codebase_context))

    # Run all agents in parallel
    results = await asyncio.gather(
        *(agent.review(review_input, context=codebase_context) for agent in agents),
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

    # Aggregate: deduplicate, sort, cap, threshold
    final = aggregate_comments(
        all_comments,
        max_comments=max_comments,
        threshold=threshold,
    )

    return final
