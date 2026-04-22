"""
Base Review Agent — Foundation for all LLM-powered code review agents.

Provides the ``ReviewAgent`` abstract base class and the ``ReviewComment``
dataclass used throughout the review pipeline. Each specialized agent
(Security, Performance, Logic, Style) inherits from ``ReviewAgent``.

Uses Google Gemini via LangChain for LLM inference.
"""

import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

logger = logging.getLogger("app.agents.base")

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ReviewComment:
    """
    A single review comment produced by an agent.

    Attributes:
        file:       Path of the file being commented on.
        line:       Line number in the diff (approximate, from LLM).
        severity:   One of: critical, warning, suggestion.
        message:    Human-readable review comment.
        agent_type: Which agent produced this comment.
    """
    file: str
    line: int
    severity: str    # critical / warning / suggestion
    message: str
    agent_type: str

    def __post_init__(self):
        """Normalize severity to lowercase and validate."""
        self.severity = self.severity.lower().strip()
        valid = {"critical", "warning", "suggestion"}
        if self.severity not in valid:
            self.severity = "suggestion"


# ---------------------------------------------------------------------------
# LLM Response Parsing
# ---------------------------------------------------------------------------

def _extract_json_from_response(text: str) -> list[dict]:
    """
    Extract JSON array from LLM response text.

    LLMs often wrap JSON in markdown code blocks or add preamble text.
    This function handles:
        - Raw JSON arrays
        - JSON wrapped in ```json ... ``` blocks
        - Single JSON objects (wrapped into a list)
        - Malformed responses (returns empty list)
    """
    # Try to find JSON in code block first
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if code_block:
        text = code_block.group(1).strip()

    # Try parsing as-is
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass

    # Try to find array pattern in text
    array_match = re.search(r"\[.*\]", text, re.DOTALL)
    if array_match:
        try:
            return json.loads(array_match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse JSON from LLM response: %s...", text[:200])
    return []


# ---------------------------------------------------------------------------
# Base Review Agent
# ---------------------------------------------------------------------------

class ReviewAgent(ABC):
    """
    Abstract base class for LLM-powered code review agents.

    Each agent has a role, a system prompt, and uses Google Gemini
    to analyze code diffs and return structured review comments.

    Subclasses must implement ``system_prompt`` property.
    """

    def __init__(
        self,
        agent_type: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
    ):
        self.agent_type = agent_type
        self._model_name = model or os.getenv("LLM_MODEL", "gemini-2.0-flash")
        self._temperature = (
            temperature if temperature is not None
            else float(os.getenv("LLM_TEMPERATURE", "0"))
        )

        self._llm = ChatGoogleGenerativeAI(
            model=self._model_name,
            temperature=self._temperature,
            google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        )

        self._prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),
            ("human", "Review this diff:\n\n{diff}"),
        ])

        self._chain = self._prompt | self._llm

        logger.debug(
            "%s agent initialized (model=%s, temp=%s)",
            self.agent_type, self._model_name, self._temperature,
        )

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        ...

    async def review(self, diff_text: str) -> list[ReviewComment]:
        """
        Analyze a code diff and return structured review comments.

        Args:
            diff_text: Formatted diff string from diff_formatter.

        Returns:
            List of ReviewComment objects found by this agent.
        """
        if not diff_text or "No reviewable" in diff_text:
            logger.info("%s: No diff to review, skipping", self.agent_type)
            return []

        start = time.monotonic()

        try:
            response = await self._chain.ainvoke({"diff": diff_text})
            raw_content = response.content

            if isinstance(raw_content, list):
                raw_text = " ".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in raw_content
                )
            else:
                raw_text = str(raw_content)

        except Exception as exc:
            logger.error(
                "%s agent LLM call failed: %s", self.agent_type, exc
            )
            return []

        elapsed = time.monotonic() - start
        logger.info(
            "%s agent completed in %.2fs (%d chars response)",
            self.agent_type, elapsed, len(raw_text),
        )
        logger.debug("%s raw response:\n%s", self.agent_type, raw_text[:500])

        # Parse LLM response into ReviewComment objects
        comments = self._parse_response(raw_text)

        logger.info(
            "%s agent found %d issues", self.agent_type, len(comments)
        )
        return comments

    def _parse_response(self, raw_text: str) -> list[ReviewComment]:
        """
        Parse raw LLM text response into ReviewComment objects.

        Handles malformed JSON gracefully — logs warnings but doesn't crash.
        """
        items = _extract_json_from_response(raw_text)
        comments: list[ReviewComment] = []

        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                comment = ReviewComment(
                    file=str(item.get("file", "unknown")),
                    line=int(item.get("line", 0)),
                    severity=str(item.get("severity", "suggestion")),
                    message=str(item.get("message", "")),
                    agent_type=self.agent_type,
                )
                if comment.message:  # skip empty messages
                    comments.append(comment)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "%s: Failed to parse comment item %s: %s",
                    self.agent_type, item, exc,
                )

        return comments
