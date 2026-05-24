import pytest
from backend.schemas import Round, TurnResponse, Proposal, OpponentScore
from backend.termination import should_terminate

def test_termination_hard_cap():
    # 5 rounds -> terminate
    rounds = [Round(number=i, working_prompt_after="p", scores_this_round={}) for i in range(1, 6)]
    term, reason = should_terminate(rounds)
    assert term is True
    assert "Hard cap of 5 rounds reached" in reason

def test_termination_empty_proposals():
    # Empty proposals in current round
    r1 = Round(
        number=1,
        defender_turn=TurnResponse(summary="R1 D", opponent_scores=[], new_proposals=[
            Proposal(id="D-R1-P1", text="p1", severity="minor", groundednessCitation="a", reasoning="r")
        ], disagreements=[]),
        challenger_turn=TurnResponse(summary="R1 C", opponent_scores=[], new_proposals=[
            Proposal(id="C-R1-P1", text="p1", severity="minor", groundednessCitation="a", reasoning="r")
        ], disagreements=[]),
        working_prompt_after="p",
        scores_this_round={}
    )
    
    r2 = Round(
        number=2,
        defender_turn=TurnResponse(summary="R2 D", opponent_scores=[], new_proposals=[], disagreements=[]),
        challenger_turn=TurnResponse(summary="R2 C", opponent_scores=[], new_proposals=[], disagreements=[]),
        working_prompt_after="p",
        scores_this_round={}
    )
    
    term, reason = should_terminate([r1, r2])
    assert term is True
    assert "Both adversaries returned empty proposals" in reason

def test_termination_convergence():
    # Convergence condition:
    # Let's say Round 1 has some proposals evaluated
    # Round 2 and Round 3:
    # Round 3 props: empty new proposals
    # Wait, let's construct rounds so actual_delta is 0.0 and max_possible_delta > 0.0
    r1 = Round(
        number=1,
        defender_turn=TurnResponse(
            summary="D", opponent_scores=[],
            new_proposals=[
                Proposal(id="D-R1-P1", adversary="defender", text="txt", severity="critical", groundednessCitation="main.py", reasoning="r")
            ],
            disagreements=[]
        ),
        challenger_turn=TurnResponse(
            summary="C", opponent_scores=[],
            new_proposals=[
                Proposal(id="C-R1-P1", adversary="challenger", text="txt", severity="minor", groundednessCitation="main.py", reasoning="r")
            ],
            disagreements=[]
        ),
        working_prompt_after="p",
        scores_this_round={"defender": 1.0, "challenger": 1.0}
    )
    
    r2 = Round(
        number=2,
        defender_turn=TurnResponse(
            summary="D", opponent_scores=[],
            new_proposals=[
                Proposal(id="D-R2-P1", adversary="defender", text="txt", severity="critical", groundednessCitation="main.py", reasoning="r")
            ],
            disagreements=[]
        ),
        challenger_turn=TurnResponse(
            summary="C", opponent_scores=[],
            new_proposals=[
                Proposal(id="C-R2-P1", adversary="challenger", text="txt", severity="minor", groundednessCitation="main.py", reasoning="r")
            ],
            disagreements=[]
        ),
        working_prompt_after="p",
        scores_this_round={"defender": 5.0, "challenger": 5.0} # sum = 10.0
    )
    
    r3 = Round(
        number=3,
        defender_turn=TurnResponse(
            summary="D", opponent_scores=[],
            new_proposals=[
                Proposal(id="D-R3-P1", adversary="defender", text="txt", severity="critical", groundednessCitation="main.py", reasoning="r")
            ],
            disagreements=[]
        ),
        challenger_turn=TurnResponse(
            summary="C", opponent_scores=[],
            new_proposals=[
                Proposal(id="C-R3-P1", adversary="challenger", text="txt", severity="minor", groundednessCitation="main.py", reasoning="r")
            ],
            disagreements=[]
        ),
        working_prompt_after="p",
        scores_this_round={"defender": 5.0, "challenger": 5.0} # sum = 10.0
    )
    
    # actual_delta = abs(10.0 - 10.0) = 0.0
    # max_possible_delta = max(t_max_R3, t_max_R2) = max(10.0 + 2.0, 10.0 + 2.0) = 12.0
    # 0.0 < 0.05 * 12.0 (0.6), so it converges!
    term, reason = should_terminate([r1, r2, r3])
    assert term is True
    assert "Score convergence" in reason

def test_termination_no_critical_important():
    # 2 consecutive rounds with only minor new proposals
    # We set different scores so actual delta = |4.0 - 0.0| = 4.0, which is >= 5% of max possible delta (4.0).
    r1 = Round(
        number=1,
        defender_turn=TurnResponse(
            summary="D", opponent_scores=[],
            new_proposals=[
                Proposal(id="D-R1-P1", adversary="defender", text="txt", severity="minor", groundednessCitation="main.py", reasoning="r")
            ],
            disagreements=[]
        ),
        challenger_turn=TurnResponse(
            summary="C", opponent_scores=[],
            new_proposals=[
                Proposal(id="C-R1-P1", adversary="challenger", text="txt", severity="minor", groundednessCitation="main.py", reasoning="r")
            ],
            disagreements=[]
        ),
        working_prompt_after="p",
        scores_this_round={"defender": 2.0, "challenger": 2.0} # sum = 4.0
    )
    
    r2 = Round(
        number=2,
        defender_turn=TurnResponse(
            summary="D", opponent_scores=[],
            new_proposals=[
                Proposal(id="D-R2-P1", adversary="defender", text="txt", severity="minor", groundednessCitation="main.py", reasoning="r")
            ],
            disagreements=[]
        ),
        challenger_turn=TurnResponse(
            summary="C", opponent_scores=[],
            new_proposals=[
                Proposal(id="C-R2-P1", adversary="challenger", text="txt", severity="minor", groundednessCitation="main.py", reasoning="r")
            ],
            disagreements=[]
        ),
        working_prompt_after="p",
        scores_this_round={"defender": 0.0, "challenger": 0.0} # sum = 0.0
    )
    
    term, reason = should_terminate([r1, r2])
    assert term is True
    assert "No critical or important proposals" in reason
