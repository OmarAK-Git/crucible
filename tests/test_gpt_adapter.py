import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import os
from backend.gpt_adapter import call_gpt_adversary
from backend.schemas import AdversaryResponse

@pytest.mark.asyncio
async def test_gpt_adapter_happy_path():
    """
    Tests that the GPT adapter correctly parses a valid JSON response from OpenAI.
    """
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"proposals": [{"text": "Clean main.py imports", "severity": "minor", "groundednessCitation": "main.py", "reasoning": "Keep imports sorted"}]}'))
        ]
        mock_response.usage = MagicMock(prompt_tokens=50, completion_tokens=100)
        
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        
        with patch("backend.gpt_adapter.AsyncOpenAI", return_value=mock_client) as mock_openai_init:
            res = await call_gpt_adversary("sys_prompt", "usr_prompt", "corpus_text")
            
            mock_openai_init.assert_called_once_with(api_key="test-openai-key")
            assert isinstance(res, AdversaryResponse)
            assert len(res.proposals) == 1
            assert res.proposals[0].text == "Clean main.py imports"
            assert res.proposals[0].severity == "minor"
            assert res.proposals[0].groundednessCitation == "main.py"

@pytest.mark.asyncio
async def test_gpt_adapter_missing_key():
    """
    Tests that the GPT adapter fails loudly if the OPENAI_API_KEY env var is missing.
    """
    # Temporarily remove OPENAI_API_KEY from environment
    with patch.dict(os.environ, {}):
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]
            
        with pytest.raises(ValueError, match="OPENAI_API_KEY environment variable is not set"):
            await call_gpt_adversary("sys_prompt", "usr_prompt", "corpus_text")
