#!/usr/bin/env python3
"""
Script d'ingestion documentaire pour NotebookLM Azure.
Usage : python ingest.py --docs-dir ./documents --force-reindex
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

from chunkers.pdf_chunker import PDFChunker
from chunkers.md_chunker import MDChunker
from chunkers.docx_chunker import DOCXChunker
from embedder import Embedder
from indexer import Indexer

SUPPORTED_EXTENSIONS = {".pdf", ".md", ".docx"}


@click.command()
@click.option("--docs-dir", required=True, type=click.Path(exists=True))
@click.option("--force-reindex", is_flag=True, default=False)
@click.option("--dry-run", is_flag=True, default=False)
def main(docs_dir: str, force_reindex: bool, dry_run: bool):
    required_env = [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
        "AZURE_SEARCH_ENDPOINT",
        "AZURE_DOCINT_ENDPOINT",
    ]
    missing = [e for e in required_env if not os.environ.get(e)]
    if missing:
        click.echo(f"Variables manquantes : {', '.join(missing)}", err=True)
        sys.exit(1)

    credential = DefaultAzureCredential()

    embedder = Embedder(endpoint=os.environ["AZURE_OPENAI_ENDPOINT"], credential=credential)
    indexer = Indexer(endpoint=os.environ["AZURE_SEARCH_ENDPOINT"], credential=credential)
    pdf_chunker = PDFChunker(endpoint=os.environ["AZURE_DOCINT_ENDPOINT"], credential=credential)
    md_chunker = MDChunker()
    docx_chunker = DOCXChunker()

    docs_path = Path(docs_dir)
    files = [
        f for f in docs_path.rglob("*")
        if f.suffix.lower() in SUPPORTED_EXTENSIONS and f.is_file()
    ]

    click.echo(f"\nDocuments trouvés : {len(files)}")
    for f in files:
        click.echo(f"  {f.relative_to(docs_path)}")

    if dry_run:
        click.echo("\nDry-run : aucune ingestion effectuée.")
        return

    indexer.ensure_index()

    indexed_hashes: set[str] = set()
    if not force_reindex:
        indexed_hashes = indexer.get_indexed_hashes()
        click.echo(f"Documents déjà indexés : {len(indexed_hashes)} hashes connus.")

    for file_path in tqdm(files, desc="Ingestion"):
        suffix = file_path.suffix.lower()
        chunker = {".pdf": pdf_chunker, ".md": md_chunker, ".docx": docx_chunker}[suffix]

        try:
            raw_chunks = list(chunker.chunk_file(str(file_path)))
        except Exception as e:
            tqdm.write(f"ERREUR chunking {file_path.name}: {e}")
            continue

        if not raw_chunks:
            tqdm.write(f"Aucun chunk extrait de {file_path.name}")
            continue

        file_hash = raw_chunks[0].file_hash
        if file_hash in indexed_hashes and not force_reindex:
            tqdm.write(f"Skipped (déjà indexé) : {file_path.name}")
            continue

        texts = [c.content for c in raw_chunks]
        try:
            embeddings = embedder.embed_chunks(texts)
        except Exception as e:
            tqdm.write(f"ERREUR embedding {file_path.name}: {e}")
            continue

        now_iso = datetime.now(timezone.utc).isoformat()

        documents = []
        for chunk, embedding in zip(raw_chunks, embeddings):
            doc_id = f"{chunk.file_hash}_{chunk.chunk_index}"
            documents.append({
                "id": doc_id,
                "content": chunk.content,
                "content_vector": embedding,
                "source_file": chunk.source_file,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "doc_type": chunk.doc_type,
                "section": chunk.section,
                "title": chunk.title,
                "file_hash": chunk.file_hash,
                "created_at": now_iso,
            })

        indexer.upload_chunks(documents)
        indexed_hashes.add(file_hash)
        tqdm.write(f"Indexé : {file_path.name} ({len(documents)} chunks)")

    click.echo("\nIngestion terminée.")


if __name__ == "__main__":
    main()
