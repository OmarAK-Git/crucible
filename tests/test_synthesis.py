from unittest.mock import patch, AsyncMock
import pytest
from backend.schemas import Round, TurnResponse, Proposal, OpponentScore
from backend.synthesis import write_final_prompt

@pytest.mark.asyncio
async def test_write_final_prompt_defender_wins():
    r1 = Round(
        number=1,
        defender_turn=TurnResponse(
            summary="D", opponent_scores=[],
            new_proposals=[Proposal(id="D-R1-P1", text="Def prop text", severity="minor", groundednessCitation="a", reasoning="r")],
            disagreements=[]
        ),
        challenger_turn=TurnResponse(
            summary="C", opponent_scores=[],
            new_proposals=[Proposal(id="C-R1-P1", text="Chal prop text", severity="minor", groundednessCitation="a", reasoning="r")],
            disagreements=[]
        ),
        working_prompt_after="p",
        scores_this_round={}
    )
    
    r2 = Round(
        number=2,
        defender_turn=TurnResponse(
            summary="D",
            opponent_scores=[OpponentScore(proposal_id="C-R1-P1", verdict="accept", reasoning="r")],
            new_proposals=[],
            disagreements=[]
        ),
        challenger_turn=None,
        working_prompt_after="p",
        scores_this_round={}
    )
    
    # Defender wins or ties
    with patch("backend.synthesis.call_claude_adversary", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = "Hardened defender prompt"
        
        res = await write_final_prompt("orig", "corpus", [r1, r2], "defender")
        assert res == "Hardened defender prompt"
        mock_claude.assert_called_once()
        # Verify content has synthetic system prompt and tracing proposals
        args = mock_claude.call_args[0]
        assert "PHASE: FINAL SYNTHESIS" in args[0]
        assert "Chal prop text" in args[1] # Check tracing original text is sent

@pytest.mark.asyncio
async def test_write_final_prompt_challenger_wins():
    r1 = Round(
        number=1,
        defender_turn=None,
        challenger_turn=None,
        working_prompt_after="p",
        scores_this_round={}
    )
    
    # Challenger wins
    with patch("backend.synthesis.call_gpt_adversary", new_callable=AsyncMock) as mock_gpt:
        mock_gpt.return_value = "Hardened challenger prompt"
        
        res = await write_final_prompt("orig", "corpus", [r1], "challenger")
        assert res == "Hardened challenger prompt"
        mock_gpt.assert_called_once()
