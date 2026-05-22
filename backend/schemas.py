from pydantic import BaseModel, Field
from typing import List, Literal

class Proposal(BaseModel):
    text: str = Field(..., description="The proposed change to the prompt")
    severity: Literal["critical", "important", "minor"] = Field(..., description="The severity level of the proposal")
    groundednessCitation: str = Field(..., description="File path, function, or line number in the corpus, or original spec")
    reasoning: str = Field(..., description="The reasoning behind the proposal")

class AdversaryResponse(BaseModel):
    proposals: List[Proposal] = Field(default_factory=list, description="List of proposals from the adversary")
