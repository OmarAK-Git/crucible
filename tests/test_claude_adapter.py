import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import os
from backend.claude_adapter import call_claude_adversary
from backend.schemas import AdversaryResponse

@pytest.mark.asyncio
async def test_claude_adapter_happy_path():
    """
    Tests that the Claude adapter correctly parses a valid JSON response from Anthropic.
    """
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-claude-key"}):
        mock_client = MagicMock()
        mock_response = MagicMock()
        
        mock_text_content = MagicMock()
        mock_text_content.text = '{"proposals": [{"text": "Fix function scope", "severity": "critical", "groundednessCitation": "auth.py:45", "reasoning": "Scope leaks"}]}'
        mock_response.content = [mock_text_content]
        mock_response.usage = MagicMock(input_tokens=40, output_tokens=80)
        
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        
        with patch("backend.claude_adapter.AsyncAnthropic", return_value=mock_client) as mock_anthropic_init:
            res = await call_claude_adversary("sys_prompt", "usr_prompt", "corpus_text")
            
            mock_anthropic_init.assert_called_once_with(api_key="test-claude-key")
            assert isinstance(res, AdversaryResponse)
            assert len(res.proposals) == 1
            assert res.proposals[0].text == "Fix function scope"
            assert res.proposals[0].severity == "critical"
            assert res.proposals[0].groundednessCitation == "auth.py:45"

@pytest.mark.asyncio
async def test_claude_adapter_missing_key():
    """
    Tests that the Claude adapter fails loudly if the ANTHROPIC_API_KEY env var is missing.
    """
    # Temporarily remove ANTHROPIC_API_KEY from environment
    with patch.dict(os.environ, {}):
        if "ANTHROPIC_API_KEY" in os.environ:
            del os.environ["ANTHROPIC_API_KEY"]
            
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY environment variable is not set"):
            await call_claude_adversary("sys_prompt", "usr_prompt", "corpus_text")
