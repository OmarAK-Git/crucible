import json
from typing import List
from .schemas import Round
from .claude_adapter import call_claude_adversary
from .gpt_adapter import call_gpt_adversary

SYNTHESIS_SYSTEM_PROMPT = """PHASE: FINAL SYNTHESIS
You won the debate by cumulative score. Your job is to write the final
hardened prompt by folding ALL ACCEPTED proposals from BOTH adversaries
into a clean, coherent prompt.
CONSTRAINTS:
- You may NOT introduce new substance. Every change in the final prompt
  must trace back to an accepted proposal in the debate history.
- You may rephrase for coherence, but the meaning of accepted proposals
  must be preserved.
- Rejected proposals are ignored. Modified proposals use the
  modification text, not the original.
- The final prompt should read as one coherent Antigravity prompt, not
  a list of accepted proposals stapled together.
- Do not add a preamble explaining what the prompt does. The prompt is
  the output.

You will be given the original prompt, the corpus, the full debate
history, and the list of accepted proposals. Return the final prompt as
plain text — no JSON, no markdown fences."""

async def write_final_prompt(original_prompt: str, corpus: str, debate_history: List[Round], winner: str) -> str:
    """
    Calls the winning adversary to generate the final synthesized prompt.
    """
    accepted_proposals = []
    # Reconstruct the set of accepted/modified proposals from the debate history
    for r in debate_history:
        for turn in [r.defender_turn, r.challenger_turn]:
            if turn:
                for score in turn.opponent_scores:
                    if score.verdict == "accept":
                        # Search for original proposal to get its text
                        prop_text = None
                        for prev_r in debate_history:
                            for prev_turn in [prev_r.defender_turn, prev_r.challenger_turn]:
                                if prev_turn:
                                    for p in prev_turn.new_proposals:
                                        if p.id == score.proposal_id:
                                            prop_text = p.text
                                            break
                        if prop_text:
                            accepted_proposals.append({
                                "id": score.proposal_id,
                                "text": prop_text,
                                "status": "accepted"
                            })
                    elif score.verdict == "modify":
                        accepted_proposals.append({
                            "id": score.proposal_id,
                            "text": score.modification,
                            "status": "modified"
                        })

    history_data = [r.model_dump() for r in debate_history]
    
    user_content = (
        f"Original Prompt:\n{original_prompt}\n\n"
        f"Codebase Corpus:\n{corpus}\n\n"
        f"Full Debate History:\n{json.dumps(history_data, indent=2)}\n\n"
        f"List of Accepted Proposals:\n{json.dumps(accepted_proposals, indent=2)}"
    )
    
    is_defender = winner.lower() in ("defender", "tied")
    
    if is_defender:
        final_prompt = await call_claude_adversary(SYNTHESIS_SYSTEM_PROMPT, user_content, "", raw_text=True)
    else:
        final_prompt = await call_gpt_adversary(SYNTHESIS_SYSTEM_PROMPT, user_content, "", raw_text=True)
        
    return final_prompt.strip()
