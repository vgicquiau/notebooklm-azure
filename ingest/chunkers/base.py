from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Chunk:
    content: str
    source_file: str
    page_number: int
    chunk_index: int
    doc_type: str
    section: str = ""
    title: str = ""
    file_hash: str = ""
