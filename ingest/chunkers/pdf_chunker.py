import hashlib
import os
import re
from typing import Iterator

import tiktoken
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, DocumentContentFormat
from azure.identity import DefaultAzureCredential
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import Chunk

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
ENCODER = tiktoken.get_encoding("cl100k_base")

# ADI insère ce commentaire entre chaque page en mode Markdown
PAGE_BREAK_RE = re.compile(r'<!--\s*PageBreak\s*-->', re.IGNORECASE)
HEADING_RE    = re.compile(r'^#{1,6}\s+(.+)$', re.MULTILINE)


def _token_count(text: str) -> int:
    return len(ENCODER.encode(text))


def _split_by_tokens(text: str, chunk_size: int, overlap: int) -> list[str]:
    tokens = ENCODER.encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunks.append(ENCODER.decode(tokens[start:end]))
        if end == len(tokens):
            break
        start += chunk_size - overlap
    return chunks


class PDFChunker:
    def __init__(self, endpoint: str, credential: DefaultAzureCredential):
        self.client = DocumentIntelligenceClient(endpoint, credential)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30),
    )
    def _analyze(self, file_bytes: bytes) -> object:
        poller = self.client.begin_analyze_document(
            "prebuilt-layout",
            AnalyzeDocumentRequest(bytes_source=file_bytes),
            output_content_format=DocumentContentFormat.MARKDOWN,
        )
        return poller.result()

    def chunk_file(self, file_path: str) -> Iterator[Chunk]:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        file_hash = hashlib.sha256(file_bytes).hexdigest()
        source_file = os.path.basename(file_path)

        result = self._analyze(file_bytes)
        markdown = result.content or ""

        # Découpe par saut de page pour conserver les numéros de page
        pages = PAGE_BREAK_RE.split(markdown)

        chunk_index  = 0
        current_title   = ""
        current_section = ""

        for page_num, page_md in enumerate(pages, start=1):
            page_md = page_md.strip()
            if not page_md:
                continue

            # Mise à jour titre/section depuis les headings de cette page
            headings = HEADING_RE.findall(page_md)
            if headings:
                if not current_title:
                    current_title = headings[0]
                current_section = headings[-1]

            if _token_count(page_md) <= CHUNK_SIZE:
                yield Chunk(
                    content=page_md,
                    source_file=source_file,
                    page_number=page_num,
                    chunk_index=chunk_index,
                    doc_type="pdf",
                    section=current_section,
                    title=current_title,
                    file_hash=file_hash,
                )
                chunk_index += 1
            else:
                for sub in _split_by_tokens(page_md, CHUNK_SIZE, CHUNK_OVERLAP):
                    yield Chunk(
                        content=sub,
                        source_file=source_file,
                        page_number=page_num,
                        chunk_index=chunk_index,
                        doc_type="pdf",
                        section=current_section,
                        title=current_title,
                        file_hash=file_hash,
                    )
                    chunk_index += 1
