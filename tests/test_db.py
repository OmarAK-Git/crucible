import pytest
from backend import db
from backend.schemas import Proposal, TurnResponse, OpponentScore, Round

def test_db_persistence_flow():
    session_id = "test-session-123"
    prompt = "Test prompt"
    corpus = "Test corpus contents"
    
    # 1. Create session
    db.create_session(session_id, prompt, corpus)
    
    # Check active list shows it
    active = db.get_active_sessions()
    assert len(active) == 1
    assert active[0]["session_id"] == session_id
    assert active[0]["status"] == "running"
    
    # Get raw session
    sess = db.get_session(session_id)
    assert sess["corpus"] == corpus
    
    # 2. Save round working prompt
    db.save_round(session_id, 1, "Working prompt 1")
    
    # 3. Save turns and proposals
    p1 = Proposal(id="D-R1-P1", adversary="defender", text="Def text", severity="critical", groundednessCitation="c1", reasoning="r1")
    db.save_turn(session_id, 1, "defender", "R1 Defender Turn Summary")
    db.save_proposals(session_id, 1, "defender", [p1])
    
    # 4. Save score
    db.save_score("D-R1-P1", session_id, 2, "challenger", "accept", "Challenger likes it")
    
    # 5. Load session state
    state = db.load_session_state(session_id)
    assert state is not None
    assert state["session_id"] == session_id
    assert state["prompt"] == prompt
    assert len(state["rounds"]) == 1
    
    r1 = state["rounds"][0]
    assert r1.number == 1
    assert r1.working_prompt_after == "Working prompt 1"
    assert r1.defender_turn is not None
    assert r1.defender_turn.summary == "R1 Defender Turn Summary"
    assert len(r1.defender_turn.new_proposals) == 1
    assert r1.defender_turn.new_proposals[0].id == "D-R1-P1"
    assert r1.defender_turn.new_proposals[0].adversary == "defender"
    
    # 6. Update session
    db.update_session(session_id, "completed", winner="defender", termination_reason="Condition triggered", final_prompt="Hardened prompt")
    
    # Re-check active list
    active = db.get_active_sessions()
    assert len(active) == 0
    
    completed_sess = db.get_session(session_id)
    assert completed_sess["status"] == "completed"
    assert completed_sess["winner"] == "defender"
    assert completed_sess["final_prompt"] == "Hardened prompt"
