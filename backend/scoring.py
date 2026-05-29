from .schemas import Proposal, Round, TurnResponse

SEVERITY_WEIGHTS = {
    "critical": 10.0,
    "important": 5.0,
    "minor": 2.0
}

ACCEPTANCE_FACTORS = {
    "accept": 1.0,
    "modify": 0.6,
    "reject": 0.0
}

def score_proposal(proposal: Proposal, opponent_verdict: str) -> float:
    """
    Computes the score for a single proposal based on severity, groundedness, and opponent verdict.
    Formula: score = severity_weight * groundedness_multiplier * acceptance_factor
    """
    severity = (proposal.severity or "minor").lower()
    sev_weight = SEVERITY_WEIGHTS.get(severity, 2.0)
    
    # Groundedness multiplier: 1.0 if not "NONE" and >= 3 characters of non-whitespace; 0.2 otherwise.
    citation = (proposal.groundednessCitation or "").strip()
    is_grounded = len(citation) >= 3 and citation.upper() != "NONE"
    ground_mult = 1.0 if is_grounded else 0.2
    
    # Acceptance factor
    verdict = (opponent_verdict or "reject").lower()
    accept_factor = ACCEPTANCE_FACTORS.get(verdict, 0.0)
    
    return sev_weight * ground_mult * accept_factor

def score_round(round_data: Round, proposals_by_id: dict) -> dict:
    """
    Calculates the scores gained by defender and challenger in this round.
    Actively rejects self-scoring with an AssertionError.
    """
    defender_gain = 0.0
    challenger_gain = 0.0
    
    # Defender's turn scores Challenger's proposals -> Challenger gets the points
    if round_data.defender_turn:
        for score_item in round_data.defender_turn.opponent_scores:
            proposal = proposals_by_id.get(score_item.proposal_id)
            if proposal:
                # Self-scoring guard using schema's fields
                assert proposal.adversary != "defender", (
                    f"Self-scoring guard failed (schema): Defender (scorer) cannot score "
                    f"their own proposal {proposal.id} (adversary: {proposal.adversary})"
                )
                challenger_gain += score_proposal(proposal, score_item.verdict)
                
    # Challenger's turn scores Defender's proposals -> Defender gets the points
    if round_data.challenger_turn:
        for score_item in round_data.challenger_turn.opponent_scores:
            proposal = proposals_by_id.get(score_item.proposal_id)
            if proposal:
                # Self-scoring guard using schema's fields
                assert proposal.adversary != "challenger", (
                    f"Self-scoring guard failed (schema): Challenger (scorer) cannot score "
                    f"their own proposal {proposal.id} (adversary: {proposal.adversary})"
                )
                defender_gain += score_proposal(proposal, score_item.verdict)
                
    return {"defender": defender_gain, "challenger": challenger_gain}
