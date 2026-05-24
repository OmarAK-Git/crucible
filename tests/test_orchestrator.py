import asyncio
from unittest.mock import patch, AsyncMock
import pytest
from backend.schemas import TurnResponse, Proposal, OpponentScore, DebateResult
from backend.orchestrator import run_debate
from backend import db

@pytest.mark.asyncio
async def test_run_debate_orchestration():
    # 1. Prepare round 1 mock results
    mock_r1_results = {
        "defender_response": {
            "proposals": [
                {"text": "Def R1 Proposal", "severity": "minor", "groundednessCitation": "main.py", "reasoning": "r"}
            ]
        },
        "challenger_response": {
            "proposals": [
                {"text": "Chal R1 Proposal", "severity": "important", "groundednessCitation": "auth.py", "reasoning": "r"}
            ]
        }
    }
    
    # 2. Prepare Defender and Challenger mock turn responses for Round 2
    # To trigger quick termination, we return empty proposals in Round 2!
    mock_def_turn = TurnResponse(
        summary="Def R2 Summary",
        opponent_scores=[
            OpponentScore(proposal_id="C-R1-P1", verdict="accept", reasoning="Looks correct")
        ],
        new_proposals=[],
        disagreements=[]
    )
    
    mock_chal_turn = TurnResponse(
        summary="Chal R2 Summary",
        opponent_scores=[
            OpponentScore(proposal_id="D-R1-P1", verdict="accept", reasoning="Accepting")
        ],
        new_proposals=[],
        disagreements=[]
    )
    
    # 3. Patch adapters and synthesize
    with patch("backend.orchestrator.run_round_1_adversaries", AsyncMock(return_value=mock_r1_results)) as mock_r1, \
         patch("backend.orchestrator.call_claude_adversary", AsyncMock(return_value=mock_def_turn)) as mock_claude, \
         patch("backend.orchestrator.call_gpt_adversary", AsyncMock(return_value=mock_chal_turn)) as mock_gpt, \
         patch("backend.orchestrator.write_final_prompt", AsyncMock(return_value="Synthesized hardened prompt")) as mock_synth:
             
         event_queue = asyncio.Queue()
         
         result = await run_debate(
             prompt="Base prompt",
             corpus="Corpus text",
             event_queue=event_queue
         )
         
         # Assertions
         assert isinstance(result, DebateResult)
         assert result.final_prompt == "Synthesized hardened prompt"
         assert len(result.rounds) == 2 # Round 1 and Round 2 (empty -> terminated)
         
         # Check database saved the session
         sess = db.get_session(result.rounds[0].defender_turn.new_proposals[0].id.split("-")[0] if False else "arbitrary")
         # We can retrieve using load_session_state on the loaded ID
         # Let's read all sessions in DB to get the generated session ID
         conn = db.get_connection()
         try:
             cur = conn.cursor()
             cur.execute("SELECT session_id, status, winner FROM sessions;")
             rows = cur.fetchall()
             assert len(rows) == 1
             session_id = rows[0][0]
             assert rows[0][1] == "completed"
             
             state = db.load_session_state(session_id)
             assert state is not None
             assert len(state["rounds"]) == 2
         finally:
             conn.close()
