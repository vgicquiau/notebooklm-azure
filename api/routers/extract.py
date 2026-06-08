import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

import httpx
from azure.search.documents import SearchClient
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from openai import AzureOpenAI
from azure.identity import get_bearer_token_provider
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

INDEX_NAME = "notebooklm-chunks"
_ADGM_BASE = os.environ.get(
    "ADGM_GRAPH_API_URL",
    "https://modernagent-adgm-dev.azurewebsites.net/api/graph",
).rstrip("/")

_jobs: dict[str, dict] = {}


class ExtractStatus(BaseModel):
    job_id: str
    status: Literal["pending", "running", "done", "error"]
    message: str = ""
    docs_total: int = 0
    docs_processed: int = 0
    entities_imported: dict = {}


_EXTRACT_SYSTEM = """You are a software architecture knowledge extractor.
Given a technical/functional document, extract entities and relationships.
Output JSON with EXACT structure:
{
  "system": {"id": "<kebab-slug>", "name": "<full name>"},
  "functional_domains": [{"id":"<DF-01 or slug>","code":"<DF-01|null>","name":"<name>","description":"<1 sentence>"}],
  "macro_functions": [{"id":"<MF-07 or slug>","code":"<code|null>","name":"<name>","mode":"<Online|Batch|MQ|Hybrid|null>","domain_id":"<matching domain id>","description":"<1 sentence>"}],
  "programs": [{"name":"<EXACT e.g. COSGN00C>","technology":"<COBOL/CICS|JCL|etc>","mode":"<Online|Batch|null>","macro_function_ids":["<mf id>"],"description":"<1 sentence>"}],
  "data_entities": [{"name":"<EXACT e.g. USRSEC>","type":"<VSAM|Db2|IMS|PS|GDG|Other>","description":"<1 sentence>"}],
  "crud_relationships": [{"program_name":"<name>","entity_name":"<name>","operations":["C","R","U","D"]}]
}
Rules:
- Use explicit codes (DF-01, MF-07) as IDs if present; else kebab-slug ("Gestion de compte" -> "gestion-de-compte")
- Include ONLY entities explicitly mentioned, NEVER invent
- Preserve exact program/file names (e.g. COSGN00C, ACTRANET)
- CRUD only if explicitly stated (e.g. in a CRUD matrix or explicit access description)
- Use empty arrays for entity types not present in the document"""


def _classify_doc(filename: str) -> str:
    fn = filename.lower()
    if "crud" in fn:
        return "crud_matrix"
    if "cartographie" in fn or "functional_overview" in fn:
        return "cartographie"
    if "c4 level 3" in fn:
        return "program_detail"
    if "c4 level 2" in fn:
        return "architecture"
    if "consolidation" in fn:
        return "consolidation"
    if "mcd " in fn:
        return "data_model"
    if "macro-mainframe" in fn or "transverse it" in fn:
        return "macro_overview"
    return "generic"


def _run_extract_job(job_id: str, credential) -> None:
    _jobs[job_id]["status"] = "running"
    _jobs[job_id]["message"] = "Nettoyage de la couche fonctionnelle existante…"
    try:
        # 0. Clear functional layer before rebuild — garantit la cohérence du graphe
        # en supprimant les entités stales (FunctionalDomain/MacroFunction/Program/DataEntity)
        # avant de recréer depuis l'intégralité des documents. Les TechnicalNode et leurs
        # annotations candidate7R sont préservés par cet endpoint.
        try:
            with httpx.Client(timeout=30.0) as http:
                r = http.delete(f"{_ADGM_BASE}/admin/functional-entities")
                if r.is_success:
                    logger.info("Functional entities cleared: %s deleted", r.json().get("deleted", "?"))
                else:
                    logger.warning("clear-functional-entities returned %s — continuing anyway", r.status_code)
        except Exception as exc:
            logger.warning("clear-functional-entities call failed: %s — continuing anyway", exc)

        _jobs[job_id]["message"] = "Lecture des documents indexés…"

        # 1. Fetch all chunks from Azure AI Search, grouped by source_file
        search_client = SearchClient(
            endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
            index_name=INDEX_NAME,
            credential=credential,
        )
        source_files: dict[str, list[tuple[int, str]]] = {}
        for result in search_client.search(
            search_text="*",
            select=["source_file", "chunk_index", "content"],
            order_by=["chunk_index asc"],
            top=5000,
        ):
            sf = result["source_file"]
            if sf not in source_files:
                source_files[sf] = []
            source_files[sf].append((result.get("chunk_index", 0), result.get("content", "")))

        docs_total = len(source_files)
        _jobs[job_id]["docs_total"] = docs_total
        _jobs[job_id]["message"] = f"{docs_total} documents trouvés — extraction en cours…"

        if docs_total == 0:
            _jobs[job_id].update(status="done", message="Aucun document trouvé dans l'index.")
            return

        # 2. GPT-4o client via managed identity / DefaultAzureCredential
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        oai = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_ad_token_provider=token_provider,
            api_version="2024-10-21",
        )
        model = os.environ["AZURE_OPENAI_GPT4O_DEPLOYMENT"]

        total_imported: dict[str, int] = {
            "systems": 0,
            "domains": 0,
            "macro_functions": 0,
            "programs": 0,
            "data_entities": 0,
            "relationships": 0,
        }

        # 3. Process each document: extract entities → push to fn-adgm-graph
        for doc_idx, (source_file, chunks) in enumerate(source_files.items()):
            _jobs[job_id]["docs_processed"] = doc_idx
            _jobs[job_id]["message"] = f"Extraction ({doc_idx + 1}/{docs_total}) : {source_file}…"

            full_text = "\n\n".join(
                c for _, c in sorted(chunks, key=lambda x: x[0])
            )
            # Trim to ~14k chars to stay within GPT-4o context budget
            if len(full_text) > 14000:
                full_text = full_text[:14000] + "\n[document tronqué]"

            try:
                resp = oai.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": _EXTRACT_SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                f"Document: {source_file}\n"
                                f"Type: {_classify_doc(source_file)}\n\n"
                                f"{full_text}"
                            ),
                        },
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_tokens=4000,
                )
                extracted = json.loads(resp.choices[0].message.content)
            except Exception as exc:
                logger.warning("GPT-4o extraction failed for %s: %s", source_file, exc)
                continue

            try:
                with httpx.Client(timeout=30.0) as http:
                    r = http.post(
                        f"{_ADGM_BASE}/admin/import-entities",
                        json=extracted,
                        headers={"Content-Type": "application/json"},
                    )
                    if r.is_success:
                        for k, v in r.json().get("imported", {}).items():
                            total_imported[k] = total_imported.get(k, 0) + v
                    else:
                        logger.warning(
                            "import-entities returned %s for %s", r.status_code, source_file
                        )
            except Exception as exc:
                logger.warning("import-entities call failed for %s: %s", source_file, exc)
                continue

        _jobs[job_id].update(
            status="done",
            docs_processed=docs_total,
            message=f"Extraction terminée — {docs_total} documents traités.",
            entities_imported=total_imported,
        )

    except Exception as exc:
        logger.exception("Extraction job %s failed: %s", job_id, exc)
        _jobs[job_id].update(status="error", message=f"Erreur : {exc}")


@router.post("/extract/graph", response_model=ExtractStatus, status_code=202)
async def start_extract(background_tasks: BackgroundTasks, request: Request):
    """Lance l'extraction asynchrone : lit l'index Search, appelle GPT-4o,
    pousse les entités dans Neo4j via fn-adgm-graph/admin/import-entities."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "pending",
        "message": "En file d'attente…",
        "docs_total": 0,
        "docs_processed": 0,
        "entities_imported": {},
    }
    background_tasks.add_task(_run_extract_job, job_id, request.app.state.credential)
    return ExtractStatus(job_id=job_id, **_jobs[job_id])


@router.get("/extract/graph/{job_id}", response_model=ExtractStatus)
async def get_extract_status(job_id: str):
    """Retourne l'état courant d'un job d'extraction."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job introuvable.")
    return ExtractStatus(job_id=job_id, **_jobs[job_id])
