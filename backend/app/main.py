"""FastAPI backend: upload PDFs, retrieve with BM25, stream grounded answers."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from .ingest import Chunk, extract_chunks  # noqa: E402
from .llm import stream_answer  # noqa: E402
from .store import DocumentStore  # noqa: E402

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
TOP_K = int(os.getenv("TOP_K", "6"))

store = DocumentStore(DATA_DIR / "store.json")
app = FastAPI(title="PDF RAG Chat")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- documents ---------------------------------------------------------------
@app.get("/api/documents")
def list_documents():
    return sorted(store.documents.values(), key=lambda d: d["uploaded_at"], reverse=True)


@app.post("/api/documents")
async def upload_documents(files: list[UploadFile] = File(...)):
    added, errors = [], []
    for f in files:
        name = f.filename or "document.pdf"
        data = await f.read()
        if not name.lower().endswith(".pdf"):
            errors.append({"file": name, "error": "Only PDF files are supported."})
            continue
        if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
            errors.append({"file": name, "error": f"File exceeds {MAX_UPLOAD_MB} MB."})
            continue
        doc_id = uuid.uuid4().hex[:12]
        try:
            chunks, pages = extract_chunks(doc_id, name, data)
        except Exception as exc:  # malformed / encrypted PDFs
            errors.append({"file": name, "error": f"Could not read PDF: {exc}"})
            continue
        if not chunks:
            errors.append(
                {"file": name, "error": "No extractable text (scanned PDF? try OCR first)."}
            )
            continue
        doc = {
            "id": doc_id,
            "name": name,
            "pages": pages,
            "chunks": len(chunks),
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        store.add(doc, chunks)
        added.append(doc)
    return {"added": added, "errors": errors}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    if not store.remove(doc_id):
        raise HTTPException(404, "Document not found")
    return {"ok": True}


# ---- chat --------------------------------------------------------------------
class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = []


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


BROAD_REQUEST = re.compile(
    r"\b(summari[sz]e|summary|overview|tl;?dr|gist|outline|main (points|ideas|topics)|"
    r"key (points|takeaways|ideas)|what (is|are) (this|these|it) about)\b",
    re.IGNORECASE,
)
OVERVIEW_K = int(os.getenv("OVERVIEW_K", "12"))


def retrieve(question: str) -> tuple[list[tuple[Chunk, float | None]], bool]:
    """Keyword search, or an even spread of passages for broad requests and
    questions whose words don't appear in the documents. Returns (hits, overview)."""
    if not BROAD_REQUEST.search(question):
        hits = store.search(question, k=TOP_K)
        if hits:
            return hits, False
    return [(c, None) for c in store.overview(OVERVIEW_K)], True


@app.post("/api/chat")
async def chat(req: ChatRequest):
    hits, overview = retrieve(req.question)
    chunks = [c for c, _ in hits]
    sources = [
        {"id": i, "doc_id": c.doc_id, "doc_name": c.doc_name, "page": c.page,
         "text": c.text, "score": None if s is None else round(s, 3)}
        for i, (c, s) in enumerate(hits, start=1)
    ]

    async def events():
        yield _sse("sources", sources)
        try:
            async for delta in stream_answer(
                req.question, chunks, [t.model_dump() for t in req.history], overview
            ):
                yield _sse("delta", delta)
        except anthropic.AuthenticationError:
            yield _sse("error", "Anthropic API key is missing or invalid. Set ANTHROPIC_API_KEY.")
        except anthropic.RateLimitError:
            yield _sse("error", "Rate limited by the Anthropic API. Try again shortly.")
        except anthropic.APIStatusError as exc:
            yield _sse("error", f"Anthropic API error ({exc.status_code}).")
        except anthropic.APIConnectionError:
            yield _sse("error", "Could not reach the Anthropic API.")
        except TypeError as exc:
            # The SDK raises TypeError when no credentials can be resolved at all.
            if "authentication" in str(exc).lower():
                yield _sse("error", "No Anthropic credentials found. Set ANTHROPIC_API_KEY in backend/.env.")
            else:
                raise
        yield _sse("done", None)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/health")
def health():
    return {"ok": True, "documents": len(store.documents), "chunks": len(store.chunks)}


# ---- serve the built React app in production ---------------------------------
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = DIST / path
        if path and target.is_file() and DIST in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
