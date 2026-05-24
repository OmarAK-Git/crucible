import asyncio
import pytest
from unittest.mock import patch, AsyncMock
from pydantic import ValidationError
from fastapi.testclient import TestClient

from backend.main import app
from backend import db
from backend.schemas import Question, TurnResponse, Proposal, OpponentScore
from backend.orchestrator import run_debate, active_sessions

client = TestClient(app)

def test_question_pydantic_validation():
    # 1. Missing fields should raise ValidationError
    with pytest.raises(ValidationError):
        Question(question="What is this?")  # Missing required fields
        
    # 2. Complete fields should succeed
    q = Question(
        question="What database to use?",
        why_it_matters="It affects latency.",
        recommended_default="SQLite",
        default_reasoning="Already set up."
    )
    assert q.question == "What database to use?"
    assert q.why_it_matters == "It affects latency."
    assert q.recommended_default == "SQLite"
    assert q.default_reasoning == "Already set up."


def test_post_answers_validation():
    session_id = "test-session-answers"
    db.create_session(session_id, "Some prompt", "Some corpus")
    
    q_id = "Q-R1-defender-1"
    q = Question(
        question="How many users?",
        why_it_matters="Affects performance.",
        recommended_default="100",
        default_reasoning="Standard default."
    )
    db.save_question(session_id, 1, "defender", q_id, q)
    
    # 1. Reject empty/whitespace answer
    response = client.post(
        f"/api/sessions/{session_id}/answers",
        json={"question_id": q_id, "answer": "   "}
    )
    assert response.status_code == 400
    assert "cannot be empty" in response.json()["detail"]
    
    # 2. Reject answers > 4000 chars
    long_ans = "x" * 4001
    response = client.post(
        f"/api/sessions/{session_id}/answers",
        json={"question_id": q_id, "answer": long_ans}
    )
    assert response.status_code == 400
    assert "cannot exceed 4000 characters" in response.json()["detail"]
    
    # 3. Reject non-existent session
    response = client.post(
        "/api/sessions/non-existent-sess/answers",
        json={"question_id": q_id, "answer": "Valid answer"}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
    
    # 4. Reject non-existent question
    response = client.post(
        f"/api/sessions/{session_id}/answers",
        json={"question_id": "non-existent-qid", "answer": "Valid answer"}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
    
    # 5. Valid answer should succeed and persist
    response = client.post(
        f"/api/sessions/{session_id}/answers",
        json={"question_id": q_id, "answer": "Valid answer"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "success", "message": "Answer saved."}
    
    # Verify DB persistence
    qas = db.get_all_question_answers(session_id)
    assert len(qas) == 1
    assert qas[0]["answer"] == "Valid answer"
    assert qas[0]["source"] == "human"


def test_post_answers_restart_edge_case():
    session_id = "test-restart-session"
    db.create_session(session_id, "Some prompt", "Some corpus")
    
    q_id = "Q-R1-defender-1"
    q = Question(
        question="Which port?",
        why_it_matters="Connection.",
        recommended_default="8000",
        default_reasoning="Standard default."
    )
    db.save_question(session_id, 1, "defender", q_id, q)
    
    # Ensure session_id is NOT in active_sessions (simulating server restart / clean memory)
    if session_id in active_sessions:
        del active_sessions[session_id]
        
    # POSTing should still succeed and persist
    response = client.post(
        f"/api/sessions/{session_id}/answers",
        json={"question_id": q_id, "answer": "9000"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    
    qas = db.get_all_question_answers(session_id)
    assert len(qas) == 1
    assert qas[0]["answer"] == "9000"
    assert qas[0]["source"] == "human"


@pytest.mark.asyncio
async def test_questions_mode_off_pauses_orchestrator():
    # Mock adapters
    # Round 1 returns a question for defender
    mock_r1_results = {
        "defender_response": {
            "proposals": [{"text": "Def R1 Proposal", "severity": "minor", "groundednessCitation": "main.py", "reasoning": "r"}],
            "questions_for_human": [
                {
                    "question": "What architecture?",
                    "why_it_matters": "Changes file structure.",
                    "recommended_default": "Monolith",
                    "default_reasoning": "Simple."
                }
            ]
        },
        "challenger_response": {
            "proposals": [{"text": "Chal R1 Proposal", "severity": "important", "groundednessCitation": "auth.py", "reasoning": "r"}],
            "questions_for_human": []
        }
    }
    
    # Round 2: empty proposals to trigger quick termination after resume
    mock_def_turn = TurnResponse(
        summary="Def R2 Summary",
        opponent_scores=[OpponentScore(proposal_id="C-R1-P1", verdict="accept", reasoning="r")],
        new_proposals=[],
        disagreements=[]
    )
    
    mock_chal_turn = TurnResponse(
        summary="Chal R2 Summary",
        opponent_scores=[OpponentScore(proposal_id="D-R1-P1", verdict="accept", reasoning="r")],
        new_proposals=[],
        disagreements=[]
    )

    with patch("backend.orchestrator.run_round_1_adversaries", AsyncMock(return_value=mock_r1_results)) as mock_r1, \
         patch("backend.orchestrator.call_claude_adversary", AsyncMock(return_value=mock_def_turn)) as mock_claude, \
         patch("backend.orchestrator.call_gpt_adversary", AsyncMock(return_value=mock_chal_turn)) as mock_gpt, \
         patch("backend.orchestrator.write_final_prompt", AsyncMock(return_value="Synthesized prompt")) as mock_synth:
             
         event_queue = asyncio.Queue()
         session_id = "test-pause-resume"
         db.create_session(session_id, "Base prompt", "Corpus text")
         debate_task = asyncio.create_task(run_debate(
             prompt="Base prompt",
             corpus="Corpus text",
             session_id=session_id,
             event_queue=event_queue,
             questions_mode="off"
         ))
         
         # Read events until we get questions_pending or timeout
         events = []
         while True:
             try:
                 event = await asyncio.wait_for(event_queue.get(), timeout=2.0)
                 events.append(event)
                 if event[0] == "questions_pending":
                     break
             except asyncio.TimeoutError:
                 break
                 
         # Verify that the session is in active_sessions and its event is not set (paused)
         assert session_id in active_sessions
         assert not active_sessions[session_id].is_set()
         
         # Check that question was saved in DB and answer is NULL
         pending = db.get_pending_questions(session_id)
         assert len(pending) == 1
         assert pending[0]["question"] == "What architecture?"
         
         # Verify event data
         pending_event = [ev for ev in events if ev[0] == "questions_pending"][0]
         assert pending_event[1]["questions"][0]["question"] == "What architecture?"
         
         # Now submit the answer using direct endpoint call to avoid blocking the event loop
         from backend.main import post_answer_endpoint, AnswerPayload
         q_id = pending[0]["question_id"]
         response = await post_answer_endpoint(
             session_id,
             AnswerPayload(question_id=q_id, answer="Microservices")
         )
         assert response.status_code == 200
         
         # Wait for the debate task to finish
         await debate_task
         
         # Verify that the answer was persisted
         qas = db.get_all_question_answers(session_id)
         assert len(qas) == 1
         assert qas[0]["answer"] == "Microservices"
         assert qas[0]["source"] == "human"


@pytest.mark.asyncio
async def test_questions_mode_on_auto_answers():
    # Mock adapters
    mock_r1_results = {
        "defender_response": {
            "proposals": [{"text": "Def R1 Proposal", "severity": "minor", "groundednessCitation": "main.py", "reasoning": "r"}],
            "questions_for_human": [
                {
                    "question": "What database?",
                    "why_it_matters": "...",
                    "recommended_default": "Postgres",
                    "default_reasoning": "..."
                }
            ]
        },
        "challenger_response": {
            "proposals": [{"text": "Chal R1 Proposal", "severity": "important", "groundednessCitation": "auth.py", "reasoning": "r"}],
            "questions_for_human": []
        }
    }
    
    mock_def_turn = TurnResponse(
        summary="Def R2 Summary",
        opponent_scores=[OpponentScore(proposal_id="C-R1-P1", verdict="accept", reasoning="r")],
        new_proposals=[],
        disagreements=[]
    )
    
    mock_chal_turn = TurnResponse(
        summary="Chal R2 Summary",
        opponent_scores=[OpponentScore(proposal_id="D-R1-P1", verdict="accept", reasoning="r")],
        new_proposals=[],
        disagreements=[]
    )

    with patch("backend.orchestrator.run_round_1_adversaries", AsyncMock(return_value=mock_r1_results)) as mock_r1, \
         patch("backend.orchestrator.call_claude_adversary", AsyncMock(return_value=mock_def_turn)) as mock_claude, \
         patch("backend.orchestrator.call_gpt_adversary", AsyncMock(return_value=mock_chal_turn)) as mock_gpt, \
         patch("backend.orchestrator.write_final_prompt", AsyncMock(return_value="Synthesized prompt")) as mock_synth:
             
         event_queue = asyncio.Queue()
         session_id = "test-auto-answers"
         db.create_session(session_id, "Base prompt", "Corpus text", questions_mode="on")
         
         # Run debate in Mode ON: it should NOT pause and should complete directly!
         await run_debate(
             prompt="Base prompt",
             corpus="Corpus text",
             session_id=session_id,
             event_queue=event_queue,
             questions_mode="on"
         )
         
         # Read all events
         events = []
         while not event_queue.empty():
             events.append(await event_queue.get())
             
         # Verify that questions_auto_answered event was emitted
         auto_events = [ev for ev in events if ev[0] == "questions_auto_answered"]
         assert len(auto_events) == 1
         assert auto_events[0][1]["answers"][0]["answer"] == "Postgres"
         assert auto_events[0][1]["answers"][0]["source"] == "auto_default"
         
         # Check DB: question has answer and is not pending
         pending = db.get_pending_questions(session_id)
         assert len(pending) == 0
         
         qas = db.get_all_question_answers(session_id)
         assert len(qas) == 1
         assert qas[0]["answer"] == "Postgres"
         assert qas[0]["source"] == "auto_default"
