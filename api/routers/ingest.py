import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

# Formats documentaires
_DOC_EXTENSIONS = {".pdf", ".md", ".docx", ".pptx", ".xlsx"}

# Formats texte brut et code source
_CODE_EXTENSIONS = {
    ".txt",
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".cpp", ".c", ".h", ".cs",
    ".go", ".rs", ".rb", ".php",
    ".sh", ".bash",
    ".yaml", ".yml", ".json", ".xml",
    ".html", ".css", ".sql",
    ".r", ".scala", ".kt", ".swift",
}

ALLOWED_EXTENSIONS = _DOC_EXTENSIONS | _CODE_EXTENSIONS
MAX_FILE_MB = 50

# Formats ZIP (DOCX, PPTX, XLSX partagent la même signature PK)
_ZIP_EXTENSIONS = {".docx", ".pptx", ".xlsx"}


class IngestStatus(BaseModel):
    job_id: str
    status: Literal["pending", "running", "done", "error"]
    filename: str
    message: str = ""
    chunks: int = 0


# Registre en mémoire des jobs d'ingestion (réinitialisé au redémarrage)
_jobs: dict[str, dict] = {}


def _check_magic_bytes(content: bytes, suffix: str) -> bool:
    """Vérifie les magic bytes du fichier pour prévenir les uploads déguisés."""
    if suffix == ".pdf":
        return content[:4] == b"%PDF"
    elif suffix in _ZIP_EXTENSIONS:
        return content[:4] == b"PK\x03\x04"
    else:
        # Texte brut / code : doit être décodable en UTF-8 (ou presque)
        try:
            content[:512].decode("utf-8")
            return True
        except (UnicodeDecodeError, ValueError):
            return False


def _run_ingest(job_id: str, filepath: Path, filename: str, credential) -> None:
    """Ingestion synchrone exécutée dans un thread de fond (BackgroundTasks)."""
    _jobs[job_id].update(status="running", message="Analyse du document…")

    try:
        from ingest.embedder import Embedder
        from ingest.indexer import Indexer

        suffix = filepath.suffix.lower()

        if suffix == ".pdf":
            from ingest.chunkers.pdf_chunker import PDFChunker
            chunker = PDFChunker(
                endpoint=os.environ["AZURE_DOCINT_ENDPOINT"],
                credential=credential,
            )
        elif suffix == ".md":
            from ingest.chunkers.md_chunker import MDChunker
            chunker = MDChunker()
        elif suffix == ".docx":
            from ingest.chunkers.docx_chunker import DOCXChunker
            chunker = DOCXChunker()
        elif suffix == ".pptx":
            from ingest.chunkers.pptx_chunker import PPTXChunker
            chunker = PPTXChunker()
        elif suffix == ".xlsx":
            from ingest.chunkers.xlsx_chunker import XLSXChunker
            chunker = XLSXChunker()
        elif suffix in _CODE_EXTENSIONS:
            from ingest.chunkers.text_chunker import TextChunker
            chunker = TextChunker(doc_type=suffix.lstrip("."))
        else:
            raise ValueError(f"Format non supporté : {suffix}")

        _jobs[job_id]["message"] = "Découpage en chunks…"
        raw_chunks = list(chunker.chunk_file(str(filepath)))

        if not raw_chunks:
            raise ValueError("Aucun contenu extrait du document.")

        indexer = Indexer(
            endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
            credential=credential,
        )
        indexer.ensure_index()
        indexed_hashes = indexer.get_indexed_hashes()
        file_hash = raw_chunks[0].file_hash

        if file_hash in indexed_hashes:
            _jobs[job_id].update(
                status="done",
                message="Document déjà indexé — aucune action nécessaire.",
                chunks=0,
            )
            return

        n = len(raw_chunks)
        _jobs[job_id]["message"] = f"Génération des embeddings ({n} chunks)…"
        embedder = Embedder(
            endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            credential=credential,
        )
        texts = [c.content for c in raw_chunks]
        embeddings = embedder.embed_chunks(texts)

        _jobs[job_id]["message"] = "Indexation dans Azure AI Search…"
        now_iso = datetime.now(timezone.utc).isoformat()
        documents = []
        for chunk, embedding in zip(raw_chunks, embeddings):
            documents.append({
                "id":             f"{chunk.file_hash}_{chunk.chunk_index}",
                "content":        chunk.content,
                "content_vector": embedding,
                "source_file":    chunk.source_file,
                "page_number":    chunk.page_number,
                "chunk_index":    chunk.chunk_index,
                "doc_type":       chunk.doc_type,
                "section":        chunk.section,
                "title":          chunk.title,
                "file_hash":      chunk.file_hash,
                "created_at":     now_iso,
            })

        indexer.upload_chunks(documents)

        _jobs[job_id].update(
            status="done",
            message=f"{len(documents)} chunks indexés avec succès.",
            chunks=len(documents),
        )

    except ImportError as e:
        logger.exception("Dépendance manquante : %s", e)
        _jobs[job_id].update(
            status="error",
            message="Dépendance manquante dans le venv API. Consultez les logs serveur.",
        )
    except Exception as e:
        logger.exception("Erreur lors de l'ingestion du document '%s' : %s", filename, e)
        _jobs[job_id].update(status="error", message="Erreur lors du traitement du document.")
    finally:
        filepath.unlink(missing_ok=True)


@router.post("/ingest", response_model=IngestStatus, status_code=202)
async def start_ingest(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            detail=f"Format non supporté. Formats acceptés : {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, detail=f"Fichier trop volumineux (max {MAX_FILE_MB} Mo).")

    if not _check_magic_bytes(content, suffix):
        raise HTTPException(
            400,
            detail=f"Le contenu du fichier ne correspond pas au format {suffix}.",
        )

    job_id = str(uuid.uuid4())
    tmp = Path(tempfile.gettempdir()) / f"nlaz_{job_id}{suffix}"
    tmp.write_bytes(content)

    _jobs[job_id] = {
        "status": "pending",
        "filename": file.filename,
        "message": "En file d'attente…",
        "chunks": 0,
    }

    background_tasks.add_task(
        _run_ingest, job_id, tmp, file.filename, request.app.state.credential
    )

    return IngestStatus(job_id=job_id, **_jobs[job_id])


@router.get("/ingest/{job_id}", response_model=IngestStatus)
async def get_ingest_status(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, detail="Job introuvable.")
    return IngestStatus(job_id=job_id, **_jobs[job_id])
