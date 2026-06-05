import hashlib
import os
from typing import Iterator

import openpyxl
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


def _row_to_text(headers: list[str], cells) -> str:
    parts = []
    for h, c in zip(headers, cells):
        val = str(c.value).strip() if c.value is not None else ""
        if val:
            parts.append(f"{h}: {val}" if h else val)
    return " | ".join(parts)


class XLSXChunker:
    def chunk_file(self, file_path: str) -> Iterator[Chunk]:
        with open(file_path, "rb") as f:
            raw_bytes = f.read()

        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        source_file = os.path.basename(file_path)

        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        chunk_index = 0

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = list(ws.iter_rows())
            if not rows:
                continue

            # Première ligne = en-têtes si au moins une cellule non vide non-générique
            raw_headers = [str(c.value).strip() if c.value is not None else "" for c in rows[0]]
            has_headers = any(h and not h.startswith("None") for h in raw_headers)
            headers = raw_headers if has_headers else [f"Col{i+1}" for i in range(len(raw_headers))]
            data_rows = rows[1:] if has_headers else rows

            buffer: list[str] = []
            buffer_tokens = 0

            for row in data_rows:
                line = _row_to_text(headers, row)
                if not line.strip():
                    continue
                t = _token_count(line)

                if buffer_tokens + t > CHUNK_SIZE and buffer:
                    yield Chunk(
                        content="\n".join(buffer),
                        source_file=source_file,
                        page_number=1,
                        chunk_index=chunk_index,
                        doc_type="xlsx",
                        section=sheet_name,
                        title=source_file,
                        file_hash=file_hash,
                    )
                    chunk_index += 1

                    overlap_buf: list[str] = []
                    ot = 0
                    for prev_line in reversed(buffer):
                        lt = _token_count(prev_line)
                        if ot + lt <= CHUNK_OVERLAP:
                            overlap_buf.insert(0, prev_line)
                            ot += lt
                        else:
                            break
                    buffer = overlap_buf
                    buffer_tokens = ot

                buffer.append(line)
                buffer_tokens += t

            if buffer:
                yield Chunk(
                    content="\n".join(buffer),
                    source_file=source_file,
                    page_number=1,
                    chunk_index=chunk_index,
                    doc_type="xlsx",
                    section=sheet_name,
                    title=source_file,
                    file_hash=file_hash,
                )
                chunk_index += 1

        wb.close()
