import hashlib
import os
from typing import Iterator

import tiktoken

from .base import Chunk

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
ENCODER = tiktoken.get_encoding("cl100k_base")


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


class TextChunker:
    """Chunker générique pour texte brut et code source."""

    def __init__(self, doc_type: str = "txt"):
        self.doc_type = doc_type

    def chunk_file(self, file_path: str) -> Iterator[Chunk]:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-1") as f:
                raw = f.read()

        if not raw.strip():
            return

        file_hash = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
        source_file = os.path.basename(file_path)

        for i, chunk_text in enumerate(_split_by_tokens(raw, CHUNK_SIZE, CHUNK_OVERLAP)):
            yield Chunk(
                content=chunk_text,
                source_file=source_file,
                page_number=1,
                chunk_index=i,
                doc_type=self.doc_type,
                section="",
                title=source_file,
                file_hash=file_hash,
            )
