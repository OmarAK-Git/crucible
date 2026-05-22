import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import os
from backend.adversary import run_round_1_adversaries
from backend.gpt_adapter import call_gpt_adversary
from backend.claude_adapter import call_claude_adversary
from backend.schemas import AdversaryResponse

@pytest.mark.asyncio
async def test_run_round_1_adversaries_happy_path():
    """
    Tests that run_round_1_adversaries concurrently triggers both Claude and GPT
    and combines their schemas into the defender/challenger dictionary.
    """
    mock_defender = AdversaryResponse(proposals=[
        {"text": "Improve auth prompt", "severity": "minor", "groundednessCitation": "auth.py", "reasoning": "R1"}
    ])
    mock_challenger = AdversaryResponse(proposals=[
        {"text": "Add input validation check", "severity": "important", "groundednessCitation": "main.py", "reasoning": "R2"}
    ])

    with patch("backend.adversary.call_claude_adversary", AsyncMock(return_value=mock_defender)) as mock_claude, \
         patch("backend.adversary.call_gpt_adversary", AsyncMock(return_value=mock_challenger)) as mock_gpt:
         
         res = await run_round_1_adversaries("prompt text", "corpus text")
         
         mock_claude.assert_called_once()
         mock_gpt.assert_called_once()
         assert res["defender_response"] == mock_defender.model_dump()
         assert res["challenger_response"] == mock_challenger.model_dump()

@pytest.mark.asyncio
async def test_gpt_malformed_json_validation():
    """
    Tests that GPT adapter raises a ValueError with the custom message
    when the raw OpenAI API response contains a malformed JSON string.
    """
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
        mock_client = MagicMock()
        mock_response = MagicMock()
        # Mocking the raw response string as a bad string (unparsable JSON)
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{ "proposals": [ { "text": "bad JSON", "severity": "minor" } '))
        ]
        mock_response.usage = None
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        
        with patch("backend.gpt_adapter.AsyncOpenAI", return_value=mock_client):
            with pytest.raises(ValueError, match="The GPT — The Challenger returned malformed JSON"):
                await call_gpt_adversary("sys_prompt", "usr_prompt", "corpus_text")

@pytest.mark.asyncio
async def test_claude_malformed_json_validation():
    """
    Tests that Claude adapter raises a ValueError with the custom message
    when the raw Anthropic API response contains a malformed JSON string.
    """
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-claude-key"}):
        mock_client = MagicMock()
        mock_response = MagicMock()
        # Mocking the raw response string as a bad string (unparsable JSON)
        mock_text_content = MagicMock()
        mock_text_content.text = '{ "proposals": [ { "text": "bad JSON", "severity": "minor" } '
        mock_response.content = [mock_text_content]
        mock_response.usage = None
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        
        with patch("backend.claude_adapter.AsyncAnthropic", return_value=mock_client):
            with pytest.raises(ValueError, match="The Claude — The Defender returned malformed JSON"):
                await call_claude_adversary("sys_prompt", "usr_prompt", "corpus_text")
