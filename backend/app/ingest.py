"""PDF text extraction and chunking."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from pypdf import PdfReader

CHUNK_CHARS = 1000
OVERLAP_CHARS = 200


@dataclass
class Chunk:
    doc_id: str
    doc_name: str
    page: int  # 1-indexed
    text: str


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"-\n(\w)", r"\1", text)  # re-join hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Split text into overlapping windows, preferring sentence/paragraph boundaries."""
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if cut > size * 0.5:
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def extract_chunks(doc_id: str, doc_name: str, data: bytes) -> tuple[list[Chunk], int]:
    """Return (chunks, page_count). Chunks never span pages so citations stay exact."""
    reader = PdfReader(io.BytesIO(data))
    chunks: list[Chunk] = []
    for i, page in enumerate(reader.pages, start=1):
        text = _clean(page.extract_text() or "")
        for piece in _split(text):
            chunks.append(Chunk(doc_id=doc_id, doc_name=doc_name, page=i, text=piece))
    return chunks, len(reader.pages)
