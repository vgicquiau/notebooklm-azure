import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from api.models.schemas import ChatRequest, ChatResponse, SourceReference
from api.services.retriever import Retriever
from api.services.generator import Generator

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_SESSION_TURNS = 20
SESSION_TTL_SECONDS = 86_400  # 24 heures d'inactivité

# Stockage in-memory — remplacer par Redis pour les déploiements multi-workers
_sessions: dict[str, dict[str, Any]] = {}


def _now() -> float:
    return time.monotonic()


def _cleanup_stale_sessions() -> None:
    """Purge les sessions inactives depuis plus de SESSION_TTL_SECONDS."""
    cutoff = _now() - SESSION_TTL_SECONDS
    stale = [sid for sid, s in _sessions.items() if s["last_access"] < cutoff]
    for sid in stale:
        del _sessions[sid]
    if stale:
        logger.debug("Sessions expirées supprimées : %d", len(stale))


def get_or_create_session(session_id: str | None) -> tuple[str, list]:
    _cleanup_stale_sessions()
    sid = session_id or str(uuid.uuid4())
    if sid not in _sessions:
        _sessions[sid] = {"history": [], "last_access": _now()}
    else:
        _sessions[sid]["last_access"] = _now()
    return sid, _sessions[sid]["history"]


@router.post("/chat", response_model=ChatResponse)
async def chat(request_data: ChatRequest, request: Request):
    retriever: Retriever = request.app.state.retriever
    generator: Generator = request.app.state.generator

    session_id, history = get_or_create_session(request_data.session_id)

    try:
        chunks = retriever.retrieve(request_data.message, top_k=request_data.top_k)
    except Exception as e:
        logger.exception("Erreur lors de la récupération des chunks : %s", e)
        raise HTTPException(status_code=503, detail="Service de recherche temporairement indisponible.")

    if not chunks:
        return ChatResponse(
            answer="Aucun document pertinent trouvé pour cette question. Vérifiez que l'ingestion a bien été effectuée.",
            session_id=session_id,
            sources=[],
            tokens_used=0,
        )

    try:
        answer, tokens_used = generator.generate(
            query=request_data.message,
            chunks=chunks,
            conversation_history=history,
            mode=request_data.mode,
            injected_notes=request_data.injected_notes,
        )
    except Exception as e:
        logger.exception("Erreur lors de la génération : %s", e)
        raise HTTPException(status_code=503, detail="Service de génération temporairement indisponible.")

    history.append({"role": "user", "content": request_data.message})
    history.append({"role": "assistant", "content": answer})

    if len(history) > MAX_SESSION_TURNS * 2:
        _sessions[session_id]["history"] = history[-(MAX_SESSION_TURNS * 2):]

    sources = [
        SourceReference(
            file=c.source_file,
            page=c.page_number,
            section=c.section,
            score=round(c.score, 4),
            content=c.content,
        )
        for c in chunks
    ]

    return ChatResponse(
        answer=answer,
        session_id=session_id,
        sources=sources,
        tokens_used=tokens_used,
    )


@router.post("/chat/clear")
async def clear_session(request: Request):
    """Purge l'historique d'une session. Le session_id est passé dans le body JSON (SEC-015)."""
    body = await request.json()
    session_id = body.get("session_id", "")
    _sessions.pop(session_id, None)
    return {"status": "cleared", "session_id": session_id}
