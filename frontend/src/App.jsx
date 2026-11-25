import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { deleteDocument, listDocuments, streamChat, uploadDocuments } from "./api.js";

const SUGGESTIONS = [
  "Summarize the main points of these documents.",
  "What are the key numbers or dates mentioned?",
  "What conclusions or recommendations are made?",
];

export default function App() {
  const [docs, setDocs] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeSource, setActiveSource] = useState(null);
  const bottomRef = useRef(null);
  const abortRef = useRef(null);

  useEffect(() => {
    listDocuments().then(setDocs).catch(() => setNotice({ type: "error", text: "Backend not reachable on :8000." }));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  async function handleFiles(fileList) {
    const files = [...fileList].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (!files.length) return setNotice({ type: "error", text: "Please choose PDF files." });
    setUploading(true);
    setNotice(null);
    try {
      const { added, errors } = await uploadDocuments(files);
      setDocs(await listDocuments());
      const parts = [];
      if (added.length) parts.push(`Indexed ${added.length} file${added.length > 1 ? "s" : ""}.`);
      for (const e of errors) parts.push(`${e.file}: ${e.error}`);
      setNotice({ type: errors.length ? "error" : "ok", text: parts.join(" ") });
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(id) {
    await deleteDocument(id);
    setDocs((d) => d.filter((x) => x.id !== id));
  }

  async function ask(question) {
    question = question.trim();
    if (!question || busy) return;
    setInput("");
    setBusy(true);

    const history = messages
      .filter((m) => !m.error)
      .map(({ role, content }) => ({ role, content }));
    setMessages((m) => [
      ...m,
      { role: "user", content: question },
      { role: "assistant", content: "", sources: [], pending: true },
    ]);

    const patchLast = (fn) =>
      setMessages((m) => {
        const copy = m.slice();
        copy[copy.length - 1] = fn(copy[copy.length - 1]);
        return copy;
      });

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamChat(
        question,
        history,
        {
          onSources: (sources) => patchLast((msg) => ({ ...msg, sources })),
          onDelta: (text) => patchLast((msg) => ({ ...msg, content: msg.content + text })),
          onError: (text) => patchLast((msg) => ({ ...msg, content: text, error: true })),
        },
        controller.signal
      );
    } catch (err) {
      if (err.name !== "AbortError") patchLast((msg) => ({ ...msg, content: err.message, error: true }));
    } finally {
      patchLast((msg) => ({ ...msg, pending: false }));
      setBusy(false);
      abortRef.current = null;
    }
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <header className="brand">
          <span className="logo">◧</span>
          <div>
            <h1>PDF RAG Chat</h1>
            <p>Ask questions, get cited answers.</p>
          </div>
        </header>

        <label
          className={`dropzone ${uploading ? "busy" : ""}`}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            handleFiles(e.dataTransfer.files);
          }}
        >
          <input
            type="file"
            accept="application/pdf"
            multiple
            hidden
            onChange={(e) => {
              handleFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <strong>{uploading ? "Indexing…" : "Drop PDFs here"}</strong>
          <span>{uploading ? "Extracting and chunking text" : "or click to browse"}</span>
        </label>

        {notice && <div className={`notice ${notice.type}`}>{notice.text}</div>}

        <h2>Documents <span className="count">{docs.length}</span></h2>
        <ul className="docs">
          {docs.length === 0 && <li className="empty">No documents yet.</li>}
          {docs.map((d) => (
            <li key={d.id}>
              <div className="doc-name" title={d.name}>{d.name}</div>
              <div className="doc-meta">
                {d.pages} pages · {d.chunks} chunks
                <button className="link" onClick={() => handleDelete(d.id)} aria-label={`Remove ${d.name}`}>
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>

        <footer className="sidebar-footer">
          <p className="privacy">
            Your PDFs are private to this tab and kept only in memory. They're deleted when you close the tab
            or after 30 minutes of inactivity.
          </p>
          <p className="credit">Built by VK</p>
        </footer>
      </aside>

      <main className="chat">
        <div className="messages">
          {messages.length === 0 ? (
            <div className="welcome">
              <h2>Chat with your PDFs</h2>
              <p>
                Upload one or more PDFs, then ask anything. Relevant passages are retrieved with BM25 and
                Claude answers using only those passages, citing them like <span className="cite static">1</span>.
              </p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} disabled={!docs.length} onClick={() => ask(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m, i) => (
              <Message key={i} msg={m} onCite={setActiveSource} />
            ))
          )}
          <div ref={bottomRef} />
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            ask(input);
          }}
        >
          <textarea
            value={input}
            rows={1}
            placeholder={docs.length ? "Ask a question about your documents…" : "Upload a PDF to get started"}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                ask(input);
              }
            }}
          />
          {busy ? (
            <button type="button" onClick={() => abortRef.current?.abort()}>Stop</button>
          ) : (
            <button type="submit" disabled={!input.trim()}>Send</button>
          )}
        </form>
      </main>

      {activeSource && (
        <div className="modal" onClick={() => setActiveSource(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <span className="cite static">{activeSource.id}</span>
              <strong>{activeSource.doc_name}</strong>
              <span className="muted">page {activeSource.page}</span>
              <button className="link" onClick={() => setActiveSource(null)}>Close</button>
            </div>
            <pre className="excerpt">{activeSource.text}</pre>
          </div>
        </div>
      )}
    </div>
  );
}

function Message({ msg, onCite }) {
  if (msg.role === "user") return <div className="msg user">{msg.content}</div>;

  const byId = Object.fromEntries((msg.sources || []).map((s) => [String(s.id), s]));
  // Turn [n] markers into links we can render as clickable citation chips.
  const md = msg.content.replace(/\[(\d+)\](?!\()/g, (all, n) => (byId[n] ? `[${n}](#cite-${n})` : all));

  return (
    <div className={`msg assistant ${msg.error ? "error" : ""}`}>
      {msg.pending && !msg.content ? (
        <div className="typing"><span /><span /><span /></div>
      ) : (
        <ReactMarkdown
          components={{
            a: ({ href, children }) => {
              const m = href?.match(/^#cite-(\d+)$/);
              if (m && byId[m[1]]) {
                return (
                  <button className="cite" onClick={() => onCite(byId[m[1]])} title={`${byId[m[1]].doc_name}, p. ${byId[m[1]].page}`}>
                    {m[1]}
                  </button>
                );
              }
              return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
            },
          }}
        >
          {md}
        </ReactMarkdown>
      )}
      {!msg.pending && msg.sources?.length > 0 && (
        <div className="sources">
          {msg.sources.map((s) => (
            <button key={s.id} className="source" onClick={() => onCite(s)}>
              <span className="cite static">{s.id}</span>
              <span className="source-name">{s.doc_name}</span>
              <span className="muted">p. {s.page}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
