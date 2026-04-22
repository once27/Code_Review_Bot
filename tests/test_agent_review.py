"""
Tests for Sprint 4 — Single Agent Review.

Unit tests for ReviewComment, JSON parsing, and GeneralReviewAgent.
All LLM calls are mocked — no actual API usage.

Run: python -m pytest tests/test_agent_review.py -v
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.base_agent import (
    ReviewComment,
    ReviewAgent,
    _extract_json_from_response,
)
from app.agents.general_agent import GeneralReviewAgent


# ---------------------------------------------------------------------------
# ReviewComment dataclass
# ---------------------------------------------------------------------------

class TestReviewComment:
    """Test ReviewComment creation and severity normalization."""

    def test_basic_creation(self):
        c = ReviewComment(
            file="app/views.py",
            line=15,
            severity="critical",
            message="SQL injection risk",
            agent_type="general",
        )
        assert c.file == "app/views.py"
        assert c.severity == "critical"

    def test_severity_normalization(self):
        c = ReviewComment("f.py", 1, "  WARNING ", "msg", "general")
        assert c.severity == "warning"

    def test_invalid_severity_defaults(self):
        c = ReviewComment("f.py", 1, "INVALID", "msg", "general")
        assert c.severity == "suggestion"

    def test_severity_case_insensitive(self):
        c = ReviewComment("f.py", 1, "CRITICAL", "msg", "general")
        assert c.severity == "critical"


# ---------------------------------------------------------------------------
# JSON Extraction from LLM responses
# ---------------------------------------------------------------------------

class TestJsonExtraction:
    """Test _extract_json_from_response with various LLM output formats."""

    def test_raw_array(self):
        text = '[{"file": "a.py", "line": 1, "severity": "warning", "message": "test"}]'
        result = _extract_json_from_response(text)
        assert len(result) == 1
        assert result[0]["file"] == "a.py"

    def test_code_block_json(self):
        text = '```json\n[{"file": "b.py", "line": 5, "severity": "critical", "message": "bad"}]\n```'
        result = _extract_json_from_response(text)
        assert len(result) == 1
        assert result[0]["severity"] == "critical"

    def test_code_block_no_lang(self):
        text = '```\n[{"file": "c.py", "line": 3, "severity": "suggestion", "message": "ok"}]\n```'
        result = _extract_json_from_response(text)
        assert len(result) == 1

    def test_single_object(self):
        text = '{"file": "d.py", "line": 10, "severity": "warning", "message": "single"}'
        result = _extract_json_from_response(text)
        assert len(result) == 1

    def test_preamble_text(self):
        text = 'Here are the issues I found:\n\n[{"file": "e.py", "line": 1, "severity": "warning", "message": "found"}]'
        result = _extract_json_from_response(text)
        assert len(result) == 1

    def test_empty_array(self):
        result = _extract_json_from_response("[]")
        assert result == []

    def test_malformed_json(self):
        result = _extract_json_from_response("this is not json at all")
        assert result == []

    def test_empty_string(self):
        result = _extract_json_from_response("")
        assert result == []


# ---------------------------------------------------------------------------
# GeneralReviewAgent (mocked LLM)
# ---------------------------------------------------------------------------

class TestGeneralReviewAgent:
    """Test GeneralReviewAgent with mocked LLM responses."""

    @pytest.fixture
    def mock_llm_response(self):
        """Create a mock LLM response with review comments."""
        return json.dumps([
            {
                "file": "app/views.py",
                "line": 15,
                "severity": "critical",
                "message": "SQL injection via string formatting",
            },
            {
                "file": "app/utils.py",
                "line": 42,
                "severity": "suggestion",
                "message": "Missing docstring",
            },
        ])

    @patch("app.agents.base_agent.ChatGoogleGenerativeAI")
    @pytest.mark.asyncio
    async def test_review_returns_comments(self, MockLLM, mock_llm_response):
        mock_response = MagicMock()
        mock_response.content = mock_llm_response

        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = mock_response

        agent = GeneralReviewAgent()
        agent._chain = mock_chain

        comments = await agent.review("some diff text")

        assert len(comments) == 2
        assert comments[0].severity == "critical"
        assert comments[0].agent_type == "general"
        assert comments[1].severity == "suggestion"

    @patch("app.agents.base_agent.ChatGoogleGenerativeAI")
    @pytest.mark.asyncio
    async def test_review_empty_diff(self, MockLLM):
        agent = GeneralReviewAgent()
        comments = await agent.review("No reviewable file changes in this PR.")
        assert comments == []

    @patch("app.agents.base_agent.ChatGoogleGenerativeAI")
    @pytest.mark.asyncio
    async def test_review_empty_string(self, MockLLM):
        agent = GeneralReviewAgent()
        comments = await agent.review("")
        assert comments == []

    @patch("app.agents.base_agent.ChatGoogleGenerativeAI")
    @pytest.mark.asyncio
    async def test_review_handles_malformed_response(self, MockLLM):
        mock_response = MagicMock()
        mock_response.content = "I found no issues with this code."

        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = mock_response

        agent = GeneralReviewAgent()
        agent._chain = mock_chain

        comments = await agent.review("some diff")
        assert comments == []

    @patch("app.agents.base_agent.ChatGoogleGenerativeAI")
    @pytest.mark.asyncio
    async def test_review_handles_llm_error(self, MockLLM):
        mock_chain = AsyncMock()
        mock_chain.ainvoke.side_effect = Exception("API rate limit")

        agent = GeneralReviewAgent()
        agent._chain = mock_chain

        comments = await agent.review("some diff")
        assert comments == []

    @patch("app.agents.base_agent.ChatGoogleGenerativeAI")
    @pytest.mark.asyncio
    async def test_review_filters_empty_messages(self, MockLLM):
        mock_response = MagicMock()
        mock_response.content = json.dumps([
            {"file": "a.py", "line": 1, "severity": "warning", "message": "real issue"},
            {"file": "b.py", "line": 2, "severity": "warning", "message": ""},
        ])

        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = mock_response

        agent = GeneralReviewAgent()
        agent._chain = mock_chain

        comments = await agent.review("some diff")
        assert len(comments) == 1

    @patch("app.agents.base_agent.ChatGoogleGenerativeAI")
    @pytest.mark.asyncio
    async def test_review_code_block_response(self, MockLLM):
        mock_response = MagicMock()
        mock_response.content = (
            "Here are the issues:\n\n"
            "```json\n"
            '[{"file": "x.py", "line": 5, "severity": "warning", "message": "issue"}]\n'
            "```"
        )

        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = mock_response

        agent = GeneralReviewAgent()
        agent._chain = mock_chain

        comments = await agent.review("diff text")
        assert len(comments) == 1
        assert comments[0].file == "x.py"

    @patch("app.agents.base_agent.ChatGoogleGenerativeAI")
    def test_agent_type(self, MockLLM):
        agent = GeneralReviewAgent()
        assert agent.agent_type == "general"

    @patch("app.agents.base_agent.ChatGoogleGenerativeAI")
    def test_system_prompt_exists(self, MockLLM):
        agent = GeneralReviewAgent()
        assert "code reviewer" in agent.system_prompt.lower()
        assert "json" in agent.system_prompt.lower()
