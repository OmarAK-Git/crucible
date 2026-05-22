from backend.adversary import build_adversary_prompt
from backend.personas import DEFENDER_PERSONA, CHALLENGER_PERSONA, ANTI_SYCOPHANCY

def test_persona_inclusion():
    """
    Verifies that the persona text and anti-sycophancy protocol are embedded
    correctly in the compiled adversary prompts.
    """
    defender_prompt = build_adversary_prompt("Defender", DEFENDER_PERSONA, "test prompt", "test corpus")
    assert DEFENDER_PERSONA in defender_prompt
    assert ANTI_SYCOPHANCY in defender_prompt
    assert "Defender" in defender_prompt

    challenger_prompt = build_adversary_prompt("Challenger", CHALLENGER_PERSONA, "test prompt", "test corpus")
    assert CHALLENGER_PERSONA in challenger_prompt
    assert ANTI_SYCOPHANCY in challenger_prompt
    assert "Challenger" in challenger_prompt
