import pytest
from backend.schemas import Proposal, Round, TurnResponse, OpponentScore
from backend.scoring import score_proposal, score_round

def test_score_proposal_rubric():
    # 1. Critical, Grounded, Accepted -> 10.0 * 1.0 * 1.0 = 10.0
    p1 = Proposal(
        id="D-R2-P1",
        adversary="defender",
        text="Critical finding",
        severity="critical",
        groundednessCitation="app.py:20",
        reasoning="re"
    )
    assert score_proposal(p1, "accept") == 10.0
    
    # 2. Important, Ungrounded, Modified -> 5.0 * 0.2 * 0.6 = 0.6
    p2 = Proposal(
        id="C-R2-P1",
        adversary="challenger",
        text="Important finding",
        severity="important",
        groundednessCitation="NONE",
        reasoning="re"
    )
    assert pytest.approx(score_proposal(p2, "modify"), 0.01) == 0.6
    
    # 3. Minor, Grounded, Rejected -> 2.0 * 1.0 * 0.0 = 0.0
    p3 = Proposal(
        id="D-R2-P2",
        adversary="defender",
        text="Minor finding",
        severity="minor",
        groundednessCitation="main.py",
        reasoning="re"
    )
    assert score_proposal(p3, "reject") == 0.0

def test_score_round_self_scoring_guard():
    # Construct a round where Defender tries to score their own proposal (ID starting with D or adversary="defender")
    p_def = Proposal(
        id="D-R2-P1",
        adversary="defender",
        text="Def proposal",
        severity="minor",
        groundednessCitation="main.py",
        reasoning="re"
    )
    proposals_by_id = {p_def.id: p_def}
    
    # Defender's turn has opponent_scores listing D-R2-P1 (self-scoring!)
    r_bad = Round(
        number=2,
        defender_turn=TurnResponse(
            summary="Def turn summary",
            opponent_scores=[
                OpponentScore(proposal_id="D-R2-P1", verdict="accept", reasoning="Looks good")
            ],
            new_proposals=[],
            disagreements=[]
        ),
        challenger_turn=None,
        working_prompt_after="prompt",
        scores_this_round={}
    )
    
    # Should raise AssertionError due to the schema's adversary matching the scorer
    with pytest.raises(AssertionError) as exc_info:
        score_round(r_bad, proposals_by_id)
    assert "Self-scoring guard failed" in str(exc_info.value)
