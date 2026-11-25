// One private workspace per browser tab. sessionStorage survives a reload but
// is cleared when the tab closes.
function makeId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
}

function getSessionId() {
  try {
    let id = sessionStorage.getItem("rag-session");
    if (!id) {
      id = makeId();
      sessionStorage.setItem("rag-session", id);
    }
    return id;
  } catch {
    // Storage blocked: keep one id for this page load.
    return (getSessionId.fallback ||= makeId());
  }
}

export const SESSION_ID = getSessionId();
const headers = (extra = {}) => ({ "X-Session-Id": SESSION_ID, ...extra });

// Tell the server the tab is closing so it can delete this session's data.
// (On a reload the next request arrives within the server's grace period and
// the data is kept.)
window.addEventListener("pagehide", () => {
  navigator.sendBeacon?.(`/api/session/${SESSION_ID}/end`);
});

export async function listDocuments() {
  const res = await fetch("/api/documents", { headers: headers() });
  if (!res.ok) throw new Error("Failed to load documents");
  return res.json();
}

export async function uploadDocuments(files) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const res = await fetch("/api/documents", { method: "POST", body: form, headers: headers() });
  if (!res.ok) throw new Error(`Upload failed (${res.status})`);
  return res.json();
}

export async function deleteDocument(id) {
  const res = await fetch(`/api/documents/${id}`, { method: "DELETE", headers: headers() });
  if (!res.ok) throw new Error("Delete failed");
}

/**
 * POST a question and consume the server-sent event stream.
 * handlers: { onSources(list), onDelta(text), onError(msg) }
 */
export async function streamChat(question, history, handlers, signal) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({ question, history }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`Chat request failed (${res.status})`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = "message";
      let data = "";
      for (const line of raw.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      const payload = data ? JSON.parse(data) : null;
      if (event === "sources") handlers.onSources?.(payload);
      else if (event === "delta") handlers.onDelta?.(payload);
      else if (event === "error") handlers.onError?.(payload);
    }
  }
}
