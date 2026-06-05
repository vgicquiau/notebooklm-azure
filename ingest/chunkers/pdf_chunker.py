import hashlib
import os
from typing import Iterator

import tiktoken
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.identity import DefaultAzureCredential
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import Chunk

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
ENCODER = tiktoken.get_encoding("cl100k_base")


def _token_count(text: str) -> int:
    return len(ENCODER.encode(text))


def _split_by_tokens(text: str, chunk_size: int, overlap: int) -> list[str]:
    tokens = ENCODER.encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(ENCODER.decode(chunk_tokens))
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
        )
        return poller.result()

    def chunk_file(self, file_path: str) -> Iterator[Chunk]:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        file_hash = hashlib.sha256(file_bytes).hexdigest()
        source_file = os.path.basename(file_path)

        result = self._analyze(file_bytes)

        paragraphs_with_meta: list[dict] = []
        current_section = ""
        current_title = ""

        if result.paragraphs:
            for para in result.paragraphs:
                role = para.role or "paragraph"
                content = para.content.strip()
                if not content:
                    continue

                page_num = 1
                if para.bounding_regions:
                    page_num = para.bounding_regions[0].page_number

                if role in ("sectionHeading", "title"):
                    current_section = content
                    if role == "title":
                        current_title = content

                paragraphs_with_meta.append({
                    "content": content,
                    "page_number": page_num,
                    "section": current_section,
                    "title": current_title,
                    "role": role,
                })

        chunk_buffer: list[str] = []
        buffer_tokens = 0
        chunk_index = 0
        page_number = 1
        section = ""
        title = ""

        def flush_buffer() -> Chunk | None:
            nonlocal chunk_index
            if not chunk_buffer:
                return None
            content = "\n\n".join(chunk_buffer)
            c = Chunk(
                content=content,
                source_file=source_file,
                page_number=page_number,
                chunk_index=chunk_index,
                doc_type="pdf",
                section=section,
                title=title,
                file_hash=file_hash,
            )
            chunk_index += 1
            return c

        for para in paragraphs_with_meta:
            para_tokens = _token_count(para["content"])

            if para_tokens > CHUNK_SIZE:
                c = flush_buffer()
                if c:
                    yield c
                chunk_buffer = []
                buffer_tokens = 0

                sub_chunks = _split_by_tokens(para["content"], CHUNK_SIZE, CHUNK_OVERLAP)
                for sub in sub_chunks:
                    yield Chunk(
                        content=sub,
                        source_file=source_file,
                        page_number=para["page_number"],
                        chunk_index=chunk_index,
                        doc_type="pdf",
                        section=para["section"],
                        title=para["title"],
                        file_hash=file_hash,
                    )
                    chunk_index += 1
                continue

            if buffer_tokens + para_tokens > CHUNK_SIZE and chunk_buffer:
                c = flush_buffer()
                if c:
                    yield c

                overlap_buffer: list[str] = []
                overlap_tokens = 0
                for p in reversed(chunk_buffer):
                    t = _token_count(p)
                    if overlap_tokens + t <= CHUNK_OVERLAP:
                        overlap_buffer.insert(0, p)
                        overlap_tokens += t
                    else:
                        break

                chunk_buffer = overlap_buffer
                buffer_tokens = overlap_tokens

            chunk_buffer.append(para["content"])
            buffer_tokens += para_tokens
            page_number = para["page_number"]
            section = para["section"]
            title = para["title"]

        c = flush_buffer()
        if c:
            yield c
