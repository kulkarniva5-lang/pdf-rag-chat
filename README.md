# PDF RAG Chat

A small, readable retrieval-augmented generation (RAG) demo: upload PDFs, ask questions, and get answers that cite the exact page each claim came from.

- **Frontend:** React + Vite. Drag-and-drop upload, streaming chat, clickable citation chips that open the source passage.
- **Backend:** Python + FastAPI. PDF text extraction (`pypdf`), page-aware chunking, BM25 retrieval (`rank-bm25`), and answers streamed from Claude over server-sent events.

```
 PDF ─► pypdf ─► page-aware chunks ─► BM25 index (in memory, per session)
                                            │
 question ─────────────────► top-k chunks ──┘
                                   │
                    numbered <source> excerpts + question
                                   │
                            Claude (streaming)
                                   │
              answer with [n] citations ─► React UI ─► click [n] to see the passage
```

## Privacy: per-session, in-memory data

Each browser tab gets its own private workspace; visitors never see each other's documents. Nothing is written to disk: the original PDF is discarded after its text is extracted, and the chunks live only in memory. A session's data is deleted when:

- the tab is closed (the page notifies the server; a reload within 15 seconds keeps the data),
- it has been inactive for `SESSION_TTL_MIN` minutes (default 30), or
- the server restarts.

Questions and retrieved passages are sent to the Anthropic API to generate answers.

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

### Docker

One container builds the React app and serves it from the Python backend:

```bash
docker build -t pdf-rag-chat .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... pdf-rag-chat
```

Open http://localhost:8000. The container listens on `$PORT` (default 8000), as most hosts expect.

### Deploy to Render (free tier)

1. On [render.com](https://render.com), choose **New → Web Service** and connect this repo.
2. Runtime: **Docker**. Instance type: **Free**.
3. Add the environment variable `ANTHROPIC_API_KEY`.
4. Deploy.

On the free tier the service sleeps after 15 minutes idle (which also clears all sessions). The app has no authentication or rate limiting, so anyone with the URL can spend your API credits. Set a spend limit on your key in the Anthropic Console before sharing the link.

## Configuration

Set these in `backend/.env`:

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Your Anthropic API key |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Model used for answers |
| `TOP_K` | `6` | Number of chunks retrieved per question |
| `MAX_UPLOAD_MB` | `25` | Per-file upload limit |
| `SESSION_TTL_MIN` | `30` | Minutes of inactivity before a session's documents are deleted |
| `MAX_SESSIONS` | `200` | Concurrent sessions kept in memory (oldest evicted beyond this) |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed origins (comma-separated) |

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/session/{id}/end` | Mark a session closed (sent by the browser on tab close) |
| `GET` | `/api/documents` | List indexed documents |
| `POST` | `/api/documents` | Upload one or more PDFs (`multipart/form-data`, field `files`) |
| `DELETE` | `/api/documents/{id}` | Remove a document and its chunks |
| `POST` | `/api/chat` | `{question, history}` → SSE stream: `sources`, then `delta`s, then `done` |

Every request except session end needs an `X-Session-Id` header (16-64 letters, digits or dashes); the frontend generates one per tab.

## Project layout

```
backend/app/
  main.py     FastAPI routes, SSE streaming, static hosting of the built UI
  ingest.py   PDF → cleaned text → overlapping chunks (never spanning pages)
  store.py    Per-session in-memory chunk stores, BM25 search, session expiry
  llm.py      Grounded prompt + streaming call to Claude
frontend/src/
  App.jsx     Upload sidebar, chat, citation chips, source viewer
  api.js      fetch helpers + SSE stream parser
scripts/
  make_sample_pdf.py   Dependency-free sample PDF generator
```

## Limitations

- Scanned (image-only) PDFs have no extractable text; run OCR first.
- Sessions live in one server process's memory, so this runs as a single instance and is meant for demo-sized corpora (hundreds of pages per session).
- There is no authentication: don't expose it publicly as-is.

## License

MIT
