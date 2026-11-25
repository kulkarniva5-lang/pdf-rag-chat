"""A tiny persistent document store with BM25 retrieval.

Everything lives in one JSON file, and the BM25 index is rebuilt in memory
whenever the corpus changes. That is plenty for a demo-sized corpus (a few
hundred pages); swap in a vector DB for anything bigger.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict
from pathlib import Path

from rank_bm25 import BM25Okapi

from .ingest import Chunk

_STOPWORDS = set(
    """a an and are as at be but by for from has have he her his i if in into is it its
    me my no not of on or our she so than that the their them then there these they this
    to was we were what when where which who why will with you your""".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS]


class DocumentStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.documents: dict[str, dict] = {}
        self.chunks: list[Chunk] = []
        self._bm25: BM25Okapi | None = None
        self._load()

    # ---- persistence -------------------------------------------------------
    def _load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.documents = raw.get("documents", {})
            self.chunks = [Chunk(**c) for c in raw.get("chunks", [])]
        self._reindex()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {"documents": self.documents, "chunks": [asdict(c) for c in self.chunks]}
            ),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def _reindex(self) -> None:
        corpus = [tokenize(c.text) for c in self.chunks]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    # ---- mutations ---------------------------------------------------------
    def add(self, doc: dict, chunks: list[Chunk]) -> None:
        with self._lock:
            self.documents[doc["id"]] = doc
            self.chunks.extend(chunks)
            self._reindex()
            self._save()

    def remove(self, doc_id: str) -> bool:
        with self._lock:
            if doc_id not in self.documents:
                return False
            del self.documents[doc_id]
            self.chunks = [c for c in self.chunks if c.doc_id != doc_id]
            self._reindex()
            self._save()
            return True

    # ---- retrieval ---------------------------------------------------------
    def overview(self, k: int = 12) -> list[Chunk]:
        """Pick chunks spread evenly through every document, for broad requests
        ("summarize", "what is this about") that keyword search can't answer."""
        by_doc: dict[str, list[Chunk]] = {}
        for c in self.chunks:
            by_doc.setdefault(c.doc_id, []).append(c)
        if not by_doc:
            return []
        per_doc = max(1, k // len(by_doc))
        picked: list[Chunk] = []
        for chunks in by_doc.values():
            n = min(per_doc, len(chunks))
            step = len(chunks) / n
            picked.extend(chunks[int(i * step)] for i in range(n))
        return picked[: max(k, len(by_doc))]

    def search(self, query: str, k: int = 6) -> list[tuple[Chunk, float]]:
        bm25 = self._bm25
        if bm25 is None:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [(self.chunks[i], float(scores[i])) for i in ranked[:k] if scores[i] > 0]
