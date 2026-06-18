from pydantic import BaseModel, Field
from typing import Annotated, Literal, Optional


# session_id : UUID v4 ou identifiant court alphanumérique généré par le frontend.
# Le pattern exclut tout caractère spécial pouvant interférer avec les requêtes SQL
# (bien que SQLite soit protégé par les placeholders, la validation reste une bonne
# pratique de défense en profondeur et prévient les abus de longueur).
_SessionId = Annotated[str, Field(max_length=64, pattern=r"^[a-zA-Z0-9_\-]{1,64}$")]

# Note injectée : limitée en taille pour éviter l'abus de la fenêtre de contexte LLM.
_Note = Annotated[str, Field(max_length=8000)]


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32000)
    session_id: Optional[_SessionId] = None
    top_k: int = Field(default=10, ge=1, le=20)
    mode: Literal["rapide", "standard", "approfondi"] = Field(default="standard")
    injected_notes: list[_Note] = Field(default_factory=list, max_length=10)


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


class GraphAction(BaseModel):
    type: Literal["highlight", "impact_paths"]
    node_ids: list[str]
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    reason: str
    query_info: Optional[dict] = None


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    sources: list[SourceReference]
    tokens_used: int
    graph_references: list[GraphReference] = Field(default_factory=list)
    graph_action: Optional[GraphAction] = None
