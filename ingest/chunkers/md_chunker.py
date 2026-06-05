import hashlib
import os
import re
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


class MDChunker:
    def chunk_file(self, file_path: str) -> Iterator[Chunk]:
        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.read()

        file_hash = hashlib.sha256(raw.encode()).hexdigest()
        source_file = os.path.basename(file_path)

        heading_pattern = re.compile(r'^(#{1,3})\s+(.+)$', re.MULTILINE)
        sections: list[dict] = []
        matches = list(heading_pattern.finditer(raw))

        if not matches:
            for i, chunk_text in enumerate(_split_by_tokens(raw, CHUNK_SIZE, CHUNK_OVERLAP)):
                yield Chunk(
                    content=chunk_text,
                    source_file=source_file,
                    page_number=1,
                    chunk_index=i,
                    doc_type="md",
                    section="",
                    title=source_file,
                    file_hash=file_hash,
                )
            return

        if matches[0].start() > 0:
            preamble = raw[:matches[0].start()].strip()
            if preamble:
                sections.append({"heading": "", "level": 0, "content": preamble})

        for i, match in enumerate(matches):
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
            content = raw[start:end].strip()
            sections.append({
                "heading": match.group(2).strip(),
                "level": len(match.group(1)),
                "content": content,
            })

        chunk_index = 0
        heading_stack: list[str] = ["", "", ""]

        for section in sections:
            if section["level"] > 0:
                heading_stack[section["level"] - 1] = section["heading"]
                for j in range(section["level"], 3):
                    heading_stack[j] = ""

            section_header = " > ".join(h for h in heading_stack if h)
            full_content = (
                f"{section['heading']}\n\n{section['content']}"
                if section["heading"]
                else section["content"]
            )

            if _token_count(full_content) <= CHUNK_SIZE:
                yield Chunk(
                    content=full_content,
                    source_file=source_file,
                    page_number=1,
                    chunk_index=chunk_index,
                    doc_type="md",
                    section=section_header,
                    title=heading_stack[0] or source_file,
                    file_hash=file_hash,
                )
                chunk_index += 1
            else:
                paragraphs = re.split(r'\n{2,}', full_content)
                buffer = ""
                for para in paragraphs:
                    candidate = f"{buffer}\n\n{para}".strip() if buffer else para
                    if _token_count(candidate) <= CHUNK_SIZE:
                        buffer = candidate
                    else:
                        if buffer:
                            yield Chunk(
                                content=buffer,
                                source_file=source_file,
                                page_number=1,
                                chunk_index=chunk_index,
                                doc_type="md",
                                section=section_header,
                                title=heading_stack[0] or source_file,
                                file_hash=file_hash,
                            )
                            chunk_index += 1
                        if _token_count(para) > CHUNK_SIZE:
                            for sub in _split_by_tokens(para, CHUNK_SIZE, CHUNK_OVERLAP):
                                yield Chunk(
                                    content=sub,
                                    source_file=source_file,
                                    page_number=1,
                                    chunk_index=chunk_index,
                                    doc_type="md",
                                    section=section_header,
                                    title=heading_stack[0] or source_file,
                                    file_hash=file_hash,
                                )
                                chunk_index += 1
                            buffer = ""
                        else:
                            buffer = para

                if buffer:
                    yield Chunk(
                        content=buffer,
                        source_file=source_file,
                        page_number=1,
                        chunk_index=chunk_index,
                        doc_type="md",
                        section=section_header,
                        title=heading_stack[0] or source_file,
                        file_hash=file_hash,
                    )
                    chunk_index += 1
