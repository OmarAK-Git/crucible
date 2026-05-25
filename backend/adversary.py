import asyncio
from typing import Optional
from .personas import DEFENDER_PERSONA, CHALLENGER_PERSONA
from .claude_adapter import call_claude_adversary
from .gpt_adapter import call_gpt_adversary

def build_adversary_prompt(role: str, persona: str, prompt: str = "", corpus: str = "") -> str:
    """
    Assembles the system prompt for the adversary.
    """
    from .personas import ANTI_SYCOPHANCY, ROUND_1_INSTRUCTIONS
    return f"Role: {role}\n\n{persona}\n\n{ANTI_SYCOPHANCY}\n\n{ROUND_1_INSTRUCTIONS}"

async def run_round_1_adversaries(
    prompt: str,
    corpus: str,
    defender_model: Optional[str] = None,
    challenger_model: Optional[str] = None
) -> dict:
    """
    Triggers both adversaries concurrently via asyncio.gather and returns their parsed outputs.
    """
    defender_system = build_adversary_prompt("Defender", DEFENDER_PERSONA, prompt, corpus)
    challenger_system = build_adversary_prompt("Challenger", CHALLENGER_PERSONA, prompt, corpus)
    
    defender_res, challenger_res = await asyncio.gather(
        call_claude_adversary(defender_system, prompt, corpus, model=defender_model),
        call_gpt_adversary(challenger_system, prompt, corpus, model=challenger_model)
    )
    
    return {
        "defender_response": defender_res.model_dump(),
        "challenger_response": challenger_res.model_dump()
    }
