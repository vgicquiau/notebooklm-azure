import logging
import os
from urllib.parse import unquote

from azure.search.documents import SearchClient
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

INDEX_NAME = "notebooklm-chunks"


class SourceSummary(BaseModel):
    source_file: str
    title: str
    summary: str
    created_at: str | None = None
    chunk_count: int = 0


class SourceChunk(BaseModel):
    chunk_index: int
    page_number: int
    section: str
    content: str


def _search_client(credential) -> SearchClient:
    return SearchClient(
        endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
        index_name=INDEX_NAME,
        credential=credential,
    )


def _odata_escape(value: str) -> str:
    return value.replace("'", "''")


@router.get("/sources", response_model=list[SourceSummary])
async def list_sources(request: Request):
    client = _search_client(request.app.state.credential)
    try:
        # Premier chunk de chaque source (chunk_index == 0) pour titre + résumé
        first_chunks: dict[str, dict] = {}
        for r in client.search(
            search_text="*",
            filter="chunk_index eq 0",
            select=["source_file", "title", "content", "created_at"],
            top=500,
        ):
            sf = r["source_file"]
            first_chunks[sf] = {
                "title": r.get("title") or sf,
                "summary": (r.get("content") or "")[:160].strip(),
                "created_at": str(r["created_at"]) if r.get("created_at") else None,
            }

        # Nombre de chunks par source via facettes
        facet_iter = client.search(
            search_text="*",
            facets=["source_file,count:500"],
            top=0,
        )
        list(facet_iter)  # consommer l'itérateur pour rendre les facettes disponibles
        counts: dict[str, int] = {
            f["value"]: f["count"]
            for f in (facet_iter.get_facets() or {}).get("source_file", [])
        }

        sources = [
            SourceSummary(
                source_file=sf,
                title=info["title"],
                summary=info["summary"],
                created_at=info["created_at"],
                chunk_count=counts.get(sf, 0),
            )
            for sf, info in first_chunks.items()
        ]
        sources.sort(key=lambda s: s.created_at or "", reverse=True)
        return sources

    except Exception:
        logger.exception("Erreur list_sources")
        raise HTTPException(500, detail="Erreur lors de la récupération des sources.")


@router.get("/sources/{source_name}/chunks", response_model=list[SourceChunk])
async def get_source_chunks(source_name: str, request: Request):
    source_name = unquote(source_name)
    client = _search_client(request.app.state.credential)
    try:
        return [
            SourceChunk(
                chunk_index=r.get("chunk_index", 0),
                page_number=r.get("page_number", 1),
                section=r.get("section", ""),
                content=r.get("content", ""),
            )
            for r in client.search(
                search_text="*",
                filter=f"source_file eq '{_odata_escape(source_name)}'",
                select=["chunk_index", "page_number", "section", "content"],
                order_by=["page_number asc", "chunk_index asc"],
                top=1000,
            )
        ]
    except Exception:
        logger.exception("Erreur get_source_chunks pour '%s'", source_name)
        raise HTTPException(500, detail="Erreur lors de la récupération du contenu.")


@router.delete("/sources/{source_name}")
async def delete_source(source_name: str, request: Request):
    source_name = unquote(source_name)
    client = _search_client(request.app.state.credential)
    try:
        ids = [
            {"id": r["id"]}
            for r in client.search(
                search_text="*",
                filter=f"source_file eq '{_odata_escape(source_name)}'",
                select=["id"],
                top=10000,
            )
        ]
        if not ids:
            raise HTTPException(404, detail="Source introuvable.")
        client.delete_documents(documents=ids)
        return {"status": "deleted", "source_file": source_name, "chunks_deleted": len(ids)}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Erreur delete_source pour '%s'", source_name)
        raise HTTPException(500, detail="Erreur lors de la suppression.")
