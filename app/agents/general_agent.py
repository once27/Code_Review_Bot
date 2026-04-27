"""
General Review Agent — Single all-purpose code reviewer.

This is an all-purpose review agent. It covers all review concerns in one pass:
security, performance, logic, and style. This is primarily for single-agent
deployments or legacy support.

Usage:
    agent = GeneralReviewAgent()
    comments = await agent.review(formatted_diff)
"""

import logging

from app.agents.base_agent import ReviewAgent

logger = logging.getLogger("app.agents.general")

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an expert code reviewer. Analyze the diff below and find issues.

For each issue found, return a JSON array where each element has these exact keys:
- "file": the filename from the diff
- "line": the approximate line number of the issue
- "severity": one of "critical", "warning", or "suggestion"
- "message": a clear, actionable description of the issue

Severity guidelines:
- critical: security vulnerabilities, data loss risk, authentication bypass, broken core logic
- warning: performance issues, bad patterns, missing error handling, potential bugs
- suggestion: style improvements, naming conventions, missing docstrings, minor improvements

Rules:
- Only comment on changed lines (lines starting with + in the diff)
- Be specific — reference the exact code pattern you're flagging
- Keep messages concise but actionable (1-2 sentences)
- If no issues found, return an empty array: []
- Return ONLY the JSON array, no other text

Example output:
```json
[
    {{
        "file": "app/auth/views.py",
        "line": 15,
        "severity": "critical",
        "message": "User input passed directly to SQL query without parameterization. Use parameterized queries to prevent SQL injection."
    }},
    {{
        "file": "app/utils.py",
        "line": 42,
        "severity": "suggestion",
        "message": "Missing docstring for public function. Add a brief description of parameters and return value."
    }}
]
```"""


# ---------------------------------------------------------------------------
# General Review Agent
# ---------------------------------------------------------------------------

class GeneralReviewAgent(ReviewAgent):
    """
    All-purpose code review agent for single-pass analysis.

    Reviews diffs for security, performance, logic, and style issues
    in a single LLM call. Will be superseded by specialized agents
    as shown in the multi-agent pipeline.
    """

    def __init__(self, **kwargs):
        super().__init__(agent_type="general", **kwargs)
        logger.info("GeneralReviewAgent ready")

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT
