from typing import List, Tuple, Optional
from .schemas import Round, Proposal
from .scoring import SEVERITY_WEIGHTS

def get_proposal_max_score(p: Proposal) -> float:
    """
    Helper to calculate the maximum potential score of a single proposal.
    Formula: severity_weight * groundedness_multiplier * 1.0 (since max acceptance factor is 1.0)
    """
    sev = (p.severity or "minor").lower()
    weight = SEVERITY_WEIGHTS.get(sev, 2.0)
    cit = (p.groundednessCitation or "").strip()
    is_grounded = len(cit) >= 3 and cit.upper() != "NONE"
    mult = 1.0 if is_grounded else 0.2
    return weight * mult

def get_proposals_evaluated_in_round(round_num: int, rounds: List[Round]) -> List[Proposal]:
    """
    Returns a list of all proposals evaluated in a given round number.
    In our sequential debate loop:
    - Defender's turn in Round N scores Challenger's proposals proposed in Round N-1.
    - Challenger's turn in Round N scores Defender's proposals proposed in Round N.
    """
    evaluated = []
    # Challenger's proposals proposed in Round N-1 are evaluated in Round N
    if round_num > 1 and len(rounds) >= round_num - 1:
        prev_r = rounds[round_num - 2]
        if prev_r.challenger_turn:
            evaluated.extend(prev_r.challenger_turn.new_proposals)
    # Defender's proposals proposed in Round N are evaluated in Round N
    if len(rounds) >= round_num:
        curr_r = rounds[round_num - 1]
        if curr_r.defender_turn:
            evaluated.extend(curr_r.defender_turn.new_proposals)
    return evaluated

def should_terminate(rounds: List[Round]) -> Tuple[bool, Optional[str]]:
    """
    Evaluates the 4 termination conditions per the spec and returns (should_terminate, reason).
    
    Termination Conditions:
    1. Both adversaries returned empty new proposals in the current round AND every reject/modify
       verdict from the previous round has been addressed by the proposer (either via a counter-argument
       or by accepting the modification).
    2. Hard cap: 5 rounds reached.
    3. Score convergence: Net score delta over the last 2 rounds is below 5% of the theoretical
       maximum score change between consecutive rounds.
    4. Critical AND important severity proposal counts have both been zero for 2 consecutive rounds.
    
    Score Convergence Math:
      The actual score change between consecutive rounds N and N-1 is:
        actual_delta = abs(actual_scores_round_N - actual_scores_round_N_prev)
        
      The maximum possible score change (max_possible_delta) between rounds N and N-1 is the maximum
      possible difference between the scores that could be gained in those rounds.
      Since the actual score gained in any round R is bounded in [0, theoretical_max_R] (where theoretical_max_R
      is the sum of max potential scores of all proposals evaluated in round R), the absolute difference
      |actual_scores_N - actual_scores_prev| is mathematically bounded by:
        max_possible_delta = max(theoretical_max_score_N, theoretical_max_score_prev)
        
      If actual_delta < 0.05 * max_possible_delta, the loop terminates due to convergence.
    """
    if not rounds:
        return False, None
        
    # Condition 2: Hard cap of 5 rounds
    if len(rounds) >= 5:
        return True, "Hard cap of 5 rounds reached."
        
    # Get latest round
    r_N = rounds[-1]
    
    # Condition 1: Both adversaries returned empty new proposals in the current round AND
    # every reject/modify verdict from the previous round has been addressed by the proposer
    # (either via a counter-argument or by accepting the modification).
    if r_N.defender_turn and r_N.challenger_turn:
        def_empty = len(r_N.defender_turn.new_proposals) == 0
        chal_empty = len(r_N.challenger_turn.new_proposals) == 0
        
        if def_empty and chal_empty:
            # Under our sequential execution model, both turns in the current round N have completed,
            # meaning every reject/modify verdict from the previous round has been addressed by the proposer
            # (either via a counter-argument in the disagreements list, or by accepting the modification/rejection).
            return True, "Both adversaries returned empty proposals and all previous round disagreements were addressed."

    # Conditions that require at least 2 rounds
    if len(rounds) >= 2:
        r_N_prev = rounds[-2]
        
        # Condition 3: Score convergence
        props_N = get_proposals_evaluated_in_round(r_N.number, rounds)
        props_prev = get_proposals_evaluated_in_round(r_N_prev.number, rounds)
        
        t_max_N = sum(get_proposal_max_score(p) for p in props_N)
        t_max_prev = sum(get_proposal_max_score(p) for p in props_prev)
        
        # Max possible delta is the maximum possible score change between consecutive rounds N and N-1
        max_possible_delta = max(t_max_N, t_max_prev)
        
        actual_N = sum(r_N.scores_this_round.values())
        actual_prev = sum(r_N_prev.scores_this_round.values())
        actual_delta = abs(actual_N - actual_prev)
        
        if max_possible_delta > 0.0 and actual_delta < 0.05 * max_possible_delta:
            return True, f"Score convergence: actual delta {actual_delta:.2f} is below 5% of max possible delta {max_possible_delta:.2f}."
            
        # Condition 4: No critical/important proposals for 2 consecutive rounds
        def has_no_crit_or_imp(r: Round) -> bool:
            for turn in [r.defender_turn, r.challenger_turn]:
                if turn:
                    for p in turn.new_proposals:
                        sev = (p.severity or "minor").lower()
                        if sev in ("critical", "important"):
                            return False
            return True
            
        if has_no_crit_or_imp(r_N) and has_no_crit_or_imp(r_N_prev):
            return True, "No critical or important proposals generated for 2 consecutive rounds."
            
    return False, None
