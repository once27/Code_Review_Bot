"""
Style Review Agent — naming, docstrings, dead code, conventions.

Focused on code cleanliness and maintainability only.
"""

import logging
from app.agents.base_agent import ReviewAgent

logger = logging.getLogger("app.agents.style")

_SYSTEM_PROMPT = """You are a style-focused code reviewer. ONLY flag code style and maintainability issues.

For each issue, return a JSON array with these exact keys:
- "file": filename from the diff
- "line": approximate line number
- "severity": "suggestion" (style issues are always suggestions)
- "message": clear, actionable description

What to look for:
- Missing or incomplete docstrings on public functions/classes
- Unclear or misleading variable/function names
- Dead code (unused imports, unreachable blocks, commented-out code)
- Magic numbers (unexplained numeric literals)
- Inconsistent naming conventions (mixing camelCase and snake_case)
- Functions that are too long (>50 lines) or do too many things
- Missing type hints on function signatures
- Spelling errors in strings, comments, or identifiers
- Redundant code that can be simplified
- Missing f-string usage (string concatenation where f-string cleaner)

Rules:
- ONLY flag style issues. Ignore security, performance, logic bugs.
- Only comment on changed lines (lines starting with +)
- Be constructive, not nitpicky — flag things that hurt readability
- If no style issues found, return: []
- Return ONLY the JSON array

Example:
```json
[
    {{
        "file": "app/models.py",
        "line": 8,
        "severity": "suggestion",
        "message": "Missing docstring for public class 'UserProfile'. Add a brief description of its purpose."
    }}
]
```"""


class StyleAgent(ReviewAgent):
    """Style and maintainability focused review agent."""

    def __init__(self, **kwargs):
        super().__init__(agent_type="style", **kwargs)
        logger.info("StyleAgent ready")

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT
