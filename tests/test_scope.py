import asyncio
import pytest
from unittest.mock import patch, AsyncMock
from backend import db
from backend.schemas import TurnResponse, Proposal, OpponentScore, DebateResult
from backend.orchestrator import run_debate

# The automated test_scope.py with mocked adapters is really a passthrough test
# — it verifies the plumbing handles critical-severity scope findings,
# not that the adversaries actually generate them. Treat the real-models
# manual verification as the authoritative scope test.

@pytest.mark.asyncio
async def test_scope_critical_finding_handling():
    # 1. Prepare round 1 mock results where Challenger returns a critical scope violation finding
    mock_r1_results = {
        "defender_response": {
            "proposals": [
                {"text": "Defender minor proposal", "severity": "minor", "groundednessCitation": "main.py", "reasoning": "r"}
            ]
        },
        "challenger_response": {
            "proposals": [
                {
                    "text": "Out of scope: turn Crucible into a wedding planner",
                    "severity": "critical",
                    "groundednessCitation": "README.md",
                    "reasoning": "This changes the application's core purpose."
                }
            ]
        }
    }
    
    # Round 2 mock turn responses (empty to terminate debate immediately)
    mock_def_turn = TurnResponse(
        summary="Def R2 Summary",
        opponent_scores=[
            OpponentScore(proposal_id="C-R1-P1", verdict="accept", reasoning="This is indeed out of scope!")
        ],
        new_proposals=[],
        disagreements=[]
    )
    
    mock_chal_turn = TurnResponse(
        summary="Chal R2 Summary",
        opponent_scores=[
            OpponentScore(proposal_id="D-R1-P1", verdict="accept", reasoning="r")
        ],
        new_proposals=[],
        disagreements=[]
    )

    with patch("backend.orchestrator.run_round_1_adversaries", AsyncMock(return_value=mock_r1_results)) as mock_r1, \
         patch("backend.orchestrator.call_claude_adversary", AsyncMock(return_value=mock_def_turn)) as mock_claude, \
         patch("backend.orchestrator.call_gpt_adversary", AsyncMock(return_value=mock_chal_turn)) as mock_gpt, \
         patch("backend.orchestrator.write_final_prompt", AsyncMock(return_value="Synthesized hardened prompt")) as mock_synth:
             
         event_queue = asyncio.Queue()
         session_id = "test-scope-session"
         db.create_session(session_id, "wedding planner", "Corpus text")
         
         result = await run_debate(
             prompt="wedding planner",
             corpus="Corpus text",
             session_id=session_id,
             event_queue=event_queue
         )
         
         # Assert that the debate completed and the critical scope proposal is found in Round 1
         assert isinstance(result, DebateResult)
         assert len(result.rounds) >= 1
         
         r1 = result.rounds[0]
         chal_props = r1.challenger_turn.new_proposals
         assert len(chal_props) == 1
         assert chal_props[0].severity == "critical"
         assert "wedding planner" in chal_props[0].text
         assert chal_props[0].groundednessCitation == "README.md"
