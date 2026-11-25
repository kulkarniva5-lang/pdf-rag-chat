# PDF RAG Chat

A small, readable retrieval-augmented generation (RAG) demo: upload PDFs, ask questions, and get answers that cite the exact page each claim came from.

- **Frontend:** React + Vite. Drag-and-drop upload, streaming chat, clickable citation chips that open the source passage.
- **Backend:** Python + FastAPI. PDF text extraction (`pypdf`), page-aware chunking, BM25 retrieval (`rank-bm25`), and answers streamed from Claude over server-sent events.

```
 PDF ─► pypdf ─► page-aware chunks ─► BM25 index (JSON on disk)
                                            │
 question ─────────────────► top-k chunks ──┘
                                   │
                    numbered <source> excerpts + question
                                   │
                            Claude (streaming)
                                   │
              answer with [n] citations ─► React UI ─► click [n] to see the passage
```

## Why BM25 instead of embeddings?

It keeps the demo dependency-light: no embedding API, no model download, no vector database. Keyword retrieval works well for questions that share vocabulary with the documents. To upgrade, replace `DocumentStore.search` in [`backend/app/store.py`](backend/app/store.py) with a vector search; the rest of the pipeline stays the same.

## Quick start

Requirements: Python 3.10+, Node 18+, and an [Anthropic API key](https://console.anthropic.com/).

**1. Backend**

```bash
cd backend
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows:     .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then put your key in .env
uvicorn app.main:app --reload --port 8000
```

**2. Frontend** (in a second terminal)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and drop in a PDF. No PDF handy? Generate a fictional employee handbook to try it with:

```bash
python scripts/make_sample_pdf.py   # writes samples/solar-handbook.pdf
```

Then ask things like *"How many vacation days carry over?"* or *"When do installation crews stop work for weather?"*

### Single-server mode

Run `npm run build` in `frontend/`, then start the backend alone: it serves the built app at http://localhost:8000.

## Configuration

Set these in `backend/.env`:

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Your Anthropic API key |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Model used for answers |
| `TOP_K` | `6` | Number of chunks retrieved per question |
| `MAX_UPLOAD_MB` | `25` | Per-file upload limit |
| `DATA_DIR` | `backend/data` | Where the index is stored |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed origins (comma-separated) |

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/documents` | List indexed documents |
| `POST` | `/api/documents` | Upload one or more PDFs (`multipart/form-data`, field `files`) |
| `DELETE` | `/api/documents/{id}` | Remove a document and its chunks |
| `POST` | `/api/chat` | `{question, history}` → SSE stream: `sources`, then `delta`s, then `done` |

## Project layout

```
backend/app/
  main.py     FastAPI routes, SSE streaming, static hosting of the built UI
  ingest.py   PDF → cleaned text → overlapping chunks (never spanning pages)
  store.py    JSON-persisted chunk store + BM25 search
  llm.py      Grounded prompt + streaming call to Claude
frontend/src/
  App.jsx     Upload sidebar, chat, citation chips, source viewer
  api.js      fetch helpers + SSE stream parser
scripts/
  make_sample_pdf.py   Dependency-free sample PDF generator
```

## Limitations

- Scanned (image-only) PDFs have no extractable text; run OCR first.
- The single-file JSON store is meant for demo-sized corpora (hundreds of pages).
- There is no authentication: don't expose it publicly as-is.

## License

MIT
