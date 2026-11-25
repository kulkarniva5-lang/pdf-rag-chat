"""In-memory, per-session document stores with BM25 retrieval.

Nothing is written to disk. Each browser session gets its own private store,
which is deleted when the tab closes, after a period of inactivity, or when
the server restarts.
"""

from __future__ import annotations

import re
import threading
import time

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
    """One session's documents and chunks, plus a BM25 index over them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.documents: dict[str, dict] = {}
        self.chunks: list[Chunk] = []
        self._bm25: BM25Okapi | None = None

    def _reindex(self) -> None:
        corpus = [tokenize(c.text) for c in self.chunks]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    # ---- mutations ---------------------------------------------------------
    def add(self, doc: dict, chunks: list[Chunk]) -> None:
        with self._lock:
            self.documents[doc["id"]] = doc
            self.chunks.extend(chunks)
            self._reindex()

    def remove(self, doc_id: str) -> bool:
        with self._lock:
            if doc_id not in self.documents:
                return False
            del self.documents[doc_id]
            self.chunks = [c for c in self.chunks if c.doc_id != doc_id]
            self._reindex()
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


class SessionManager:
    """Maps session ids to stores and expires them.

    Every request pushes a session's expiry out to `ttl` seconds. When the tab
    closes, the browser calls `end()`, which shortens the expiry to `grace`
    seconds; a page reload makes a new request within that window and keeps
    the session alive.
    """

    def __init__(self, ttl: float, grace: float, max_sessions: int) -> None:
        self.ttl, self.grace, self.max_sessions = ttl, grace, max_sessions
        self._lock = threading.Lock()
        self._sessions: dict[str, tuple[DocumentStore, float]] = {}

    def get(self, session_id: str) -> DocumentStore:
        now = time.monotonic()
        with self._lock:
            store = self._sessions.get(session_id, (None, 0))[0]
            if store is None:
                if len(self._sessions) >= self.max_sessions:
                    # Evict the session closest to expiring to bound memory use.
                    oldest = min(self._sessions, key=lambda s: self._sessions[s][1])
                    del self._sessions[oldest]
                store = DocumentStore()
            self._sessions[session_id] = (store, now + self.ttl)
            return store

    def end(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._sessions:
                store, _ = self._sessions[session_id]
                self._sessions[session_id] = (store, time.monotonic() + self.grace)

    def purge_expired(self) -> int:
        now = time.monotonic()
        with self._lock:
            expired = [s for s, (_, exp) in self._sessions.items() if exp <= now]
            for s in expired:
                del self._sessions[s]
            return len(expired)

    def __len__(self) -> int:
        return len(self._sessions)
