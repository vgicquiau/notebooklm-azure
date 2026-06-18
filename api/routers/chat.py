import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from api.services.rate_limiter import check_rate_limit

from api.models.schemas import ChatRequest, ChatResponse, GraphAction, GraphReference, SourceReference
from api.services import compactor, session_store
from api.services.retriever import Retriever
from api.services.generator import Generator

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(check_rate_limit)])
async def chat(request_data: ChatRequest, request: Request):
    retriever: Retriever = request.app.state.retriever
    generator: Generator = request.app.state.generator

    session_store.cleanup_stale_sessions()
    session_id = session_store.get_or_create_session(request_data.session_id)
    history = session_store.get_history_for_llm(session_id)

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
            graph_references=[],
        )

    try:
        answer, tokens_used, graph_refs, graph_action = generator.generate(
            query=request_data.message,
            chunks=chunks,
            conversation_history=history,
            mode=request_data.mode,
            injected_notes=request_data.injected_notes,
        )
    except Exception as e:
        logger.exception("Erreur lors de la génération : %s", e)
        raise HTTPException(status_code=503, detail="Service de génération temporairement indisponible.")

    # content tronqué à 2000 chars (SEC-009) : évite l'exfiltration du corpus
    # complet par accumulation de réponses — suffisant pour l'affichage des citations.
    sources = [
        SourceReference(
            file=c.source_file,
            page=c.page_number,
            section=c.section,
            score=round(c.score, 4),
            content=c.content[:2000],
        )
        for c in chunks
    ]

    session_store.append_message(session_id, "user", request_data.message, mode=request_data.mode)
    session_store.append_message(
        session_id, "assistant", answer,
        citations=[s.model_dump() for s in sources],
        mode=request_data.mode,
        tokens_used=tokens_used,
    )

    if compactor.should_compact(session_id):
        compactor.compact_session(session_id, generator)

    return ChatResponse(
        answer=answer,
        session_id=session_id,
        sources=sources,
        tokens_used=tokens_used,
        graph_references=[GraphReference(**ref) for ref in graph_refs],
        graph_action=GraphAction(**graph_action) if graph_action else None,
    )


@router.get("/chat/history/{session_id}")
async def get_chat_history(session_id: str):
    """Historique complet d'une session, pour ré-hydrater le frontend après un reload."""
    return {
        "messages": session_store.get_full_history_for_ui(session_id),
        "summary": session_store.get_summary(session_id),
    }


@router.post("/chat/clear")
async def clear_session(request: Request):
    """Purge l'historique d'une session. Le session_id est passé dans le body JSON (SEC-015)."""
    body = await request.json()
    session_id = body.get("session_id", "")
    session_store.clear_session(session_id)
    return {"status": "cleared", "session_id": session_id}
