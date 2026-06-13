from pydantic import BaseModel, Field
from typing import Literal, Optional


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32000)
    session_id: Optional[str] = Field(default=None)
    top_k: int = Field(default=10, ge=1, le=20)
    mode: Literal["rapide", "standard", "approfondi"] = Field(default="standard")
    injected_notes: list[str] = Field(default_factory=list)


class SourceReference(BaseModel):
    file: str
    page: int
    section: str
    score: float
    content: str = ""


class GraphReference(BaseModel):
    id: str
    kind: Literal["entity", "community"]
    type: Optional[str] = None
    nom: str


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    sources: list[SourceReference]
    tokens_used: int
    graph_references: list[GraphReference] = Field(default_factory=list)
