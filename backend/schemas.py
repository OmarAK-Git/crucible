from pydantic import BaseModel, Field
from typing import List, Literal, Optional

class Question(BaseModel):
    question: str = Field(..., description="The question in plain English")
    why_it_matters: str = Field(..., description="Why this question matters (one sentence)")
    recommended_default: str = Field(..., description="The recommended default answer")
    default_reasoning: str = Field(..., description="Reasoning for the recommended default")

class QuestionAnswer(BaseModel):
    question_id: str = Field(..., description="Generated ID: Q-R{n}-{adversary}-{idx}")
    answer: str = Field(..., description="The human or auto-selected answer")
    source: str = Field(..., description="human or auto_default")

class Proposal(BaseModel):
    id: Optional[str] = Field(default=None, description="Deterministic ID assigned by the orchestrator, e.g. D-R2-P1")
    adversary: Optional[Literal["defender", "challenger"]] = Field(default=None, description="The adversary who proposed this ('defender' or 'challenger')")
    text: str = Field(..., description="The proposed change to the prompt")
    severity: Literal["critical", "important", "minor"] = Field(..., description="The severity level of the proposal")
    groundednessCitation: str = Field(..., description="File path, function, or line number in the corpus, or original spec")
    reasoning: str = Field(..., description="The reasoning behind the proposal")

class AdversaryResponse(BaseModel):
    proposals: List[Proposal] = Field(default_factory=list, description="List of proposals from the adversary")
    questions_for_human: List[Question] = Field(default_factory=list, description="Questions for the human if any")

class OpponentScore(BaseModel):
    proposal_id: str = Field(..., description="The ID of the opponent's proposal being scored")
    verdict: Literal["accept", "modify", "reject"] = Field(..., description="Score verdict")
    reasoning: str = Field(..., description="Reasoning for the score")
    modification: Optional[str] = Field(default=None, description="Suggested modification text, required if verdict is modify")

class TurnResponse(BaseModel):
    summary: str = Field(..., description="Text summary of the turn analysis")
    opponent_scores: List[OpponentScore] = Field(default_factory=list, description="Scores for the opponent's previous proposals")
    new_proposals: List[Proposal] = Field(default_factory=list, description="New proposals from this turn")
    disagreements: List[str] = Field(default_factory=list, description="List of open/counter-arg disagreements that proposer has addressed")
    questions_for_human: List[Question] = Field(default_factory=list, description="Questions for the human if any")

class Round(BaseModel):
    number: int = Field(..., description="Round number")
    defender_turn: Optional[TurnResponse] = Field(default=None, description="Defender's turn response")
    challenger_turn: Optional[TurnResponse] = Field(default=None, description="Challenger's turn response")
    working_prompt_after: str = Field(..., description="Working prompt state after this round's proposals are merged")
    scores_this_round: dict = Field(default_factory=dict, description="Defender and challenger scores gained in this round")

class DebateResult(BaseModel):
    rounds: List[Round] = Field(default_factory=list, description="List of debate rounds")
    final_prompt: str = Field(..., description="Final synthesized prompt")
    winner: Literal["defender", "challenger", "tied"] = Field(..., description="Who won the debate")
    termination_reason: str = Field(..., description="Why the debate terminated")
    defender_score: float = Field(..., description="Cumulative Defender score")
    challenger_score: float = Field(..., description="Cumulative Challenger score")
