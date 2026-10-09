"use client";

import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "../lib/api";

type Document = {
  id: string;
  filename: string;
  status: string;
  chunk_count: number;
  embedding_version: string | null;
};
type Chunk = {
  id: string;
  content: string;
  page: number | null;
  filename?: string;
  score?: number;
  rank?: number;
  citation_id?: string;
};
type SearchResult = {
  items: Chunk[];
  score_type: string;
  retrieval_ms: number;
};
type Capabilities = {
  private_uploads_enabled: boolean;
  embedding_model_configured: boolean;
};

export default function CorpusWorkspace({
  onChange,
}: {
  onChange: () => void;
}) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [selected, setSelected] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [question, setQuestion] = useState("");
  const [strategy, setStrategy] = useState("keyword");
  const [topK, setTopK] = useState(5);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [chunks, setChunks] = useState<Chunk[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [docs, config] = await Promise.all([
        apiRequest<{ items: Document[] }>("/documents?limit=100"),
        apiRequest<Capabilities>("/capabilities"),
      ]);
      setDocuments(docs.items);
      setCapabilities(config);
      setSelected((current) =>
        docs.items.some((doc) => doc.id === current)
          ? current
          : (docs.items[0]?.id ?? ""),
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to load documents.",
      );
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  const current = documents.find((doc) => doc.id === selected);
  async function upload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    const form = event.currentTarget;
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      const data = new FormData();
      data.append("file", file);
      const doc = await apiRequest<Document>("/documents", {
        method: "POST",
        body: data,
      });
      await refresh();
      setSelected(doc.id);
      setResult(null);
      setChunks(null);
      setMessage(
        `Indexed ${doc.filename} into ${doc.chunk_count} chunks for keyword search.`,
      );
      form.reset();
      setFile(null);
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }
  async function search(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await apiRequest<SearchResult>("/search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question,
            document_id: selected,
            strategy,
            top_k: topK,
          }),
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed.");
    } finally {
      setBusy(false);
    }
  }
  async function inspect() {
    setBusy(true);
    setError(null);
    try {
      setChunks(
        (
          await apiRequest<{ items: Chunk[] }>(
            `/documents/${selected}/chunks?limit=100`,
          )
        ).items,
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to inspect chunks.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function indexVectors() {
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      await apiRequest(`/documents/${selected}/index`, { method: "POST" });
      await refresh();
      setMessage("Vector indexing completed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Vector indexing failed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section id="documents">
      <div className="section-heading">
        <div>
          <span className="eyebrow">CORPUS & RETRIEVAL</span>
          <h2>Find your evidence</h2>
        </div>
        <button onClick={() => void refresh()} disabled={busy || loading}>
          Reload documents
        </button>
      </div>
      <p className="muted">
        Upload a text-based PDF, TXT, or Markdown file (up to 5 MiB). Retrieval
        returns source chunks; it does not generate an answer.
      </p>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {message && <p role="status">{message}</p>}
      {loading ? (
        <p role="status">Loading documents…</p>
      ) : (
        <>
          {capabilities?.private_uploads_enabled ? (
            <form className="upload-form" onSubmit={upload}>
              <label htmlFor="upload">Document file</label>
              <input
                id="upload"
                type="file"
                accept=".pdf,.txt,.md"
                required
                disabled={busy}
                onChange={(event) => {
                  const chosen = event.target.files?.[0] ?? null;
                  if (chosen && chosen.size > 5 * 1024 * 1024) {
                    setError("Files must be no larger than 5 MiB.");
                    setFile(null);
                    event.target.value = "";
                  } else {
                    setFile(chosen);
                    setError(null);
                  }
                }}
              />
              <button type="submit" disabled={busy || !file}>
                {busy ? "Working…" : "Upload and index"}
              </button>
            </form>
          ) : (
            <p className="notice">
              Document uploads are disabled in read-only mode.
            </p>
          )}
          {documents.length === 0 ? (
            <div className="empty">
              <h3>No documents yet</h3>
              <p>
                Upload the original sample-corpus/retrieval-notes.md from the
                repository to get started.
              </p>
            </div>
          ) : (
            <>
              <label htmlFor="document">Search document (latest 100)</label>
              <select
                id="document"
                value={selected}
                disabled={busy}
                onChange={(event) => {
                  setSelected(event.target.value);
                  setStrategy("keyword");
                  setResult(null);
                  setChunks(null);
                  setMessage("");
                }}
              >
                {documents.map((doc) => (
                  <option key={doc.id} value={doc.id}>
                    {doc.filename} · {doc.chunk_count} chunks · {doc.status}
                  </option>
                ))}
              </select>
              <div className="document-actions">
                <button onClick={() => void inspect()} disabled={busy}>
                  Inspect chunks
                </button>
                {capabilities?.private_uploads_enabled && (
                  <button
                    onClick={() => void indexVectors()}
                    disabled={busy || !capabilities.embedding_model_configured}
                  >
                    {current?.embedding_version
                      ? "Re-index vectors"
                      : "Index vectors"}
                  </button>
                )}
                <small>
                  {capabilities?.embedding_model_configured
                    ? "Local model configured"
                    : "Vector model unavailable; see README setup"}
                </small>
              </div>
              {chunks && (
                <details open>
                  <summary>Source chunks (first 100)</summary>
                  {chunks.map((chunk) => (
                    <article className="source-chunk" key={chunk.id}>
                      <small>
                        Chunk {chunk.id}
                        {chunk.page ? ` · Page ${chunk.page}` : ""}
                      </small>
                      <p>{chunk.content}</p>
                    </article>
                  ))}
                </details>
              )}
              <form className="search-form" onSubmit={search}>
                <label htmlFor="question">Question or search terms</label>
                <textarea
                  id="question"
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  maxLength={2000}
                  required
                  disabled={busy}
                  placeholder="What does PostgreSQL full-text search measure?"
                />
                <div className="search-options">
                  <label>
                    Strategy
                    <select
                      value={strategy}
                      onChange={(event) => {
                        setStrategy(event.target.value);
                        setResult(null);
                      }}
                      disabled={busy}
                    >
                      <option value="keyword">PostgreSQL full-text</option>
                      <option
                        value="vector"
                        disabled={!current?.embedding_version}
                      >
                        Vector cosine similarity
                      </option>
                      <option
                        value="hybrid"
                        disabled={!current?.embedding_version}
                      >
                        Hybrid RRF
                      </option>
                    </select>
                  </label>
                  <label>
                    Top K
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={topK}
                      onChange={(event) => setTopK(Number(event.target.value))}
                      required
                      disabled={busy}
                    />
                  </label>
                  <button type="submit" disabled={busy || !question.trim()}>
                    Search evidence
                  </button>
                </div>
              </form>
              {result && (
                <div aria-live="polite">
                  <p className="muted">
                    {result.items.length} matching chunks ·{" "}
                    {result.retrieval_ms.toFixed(2)} ms · {result.score_type}
                  </p>
                  {result.items.length === 0 ? (
                    <p>
                      No matching evidence found. Try different terms; keyword
                      search can miss paraphrases.
                    </p>
                  ) : (
                    result.items.map((chunk) => (
                      <article className="source-chunk" key={chunk.id}>
                        <div className="section-heading">
                          <strong>
                            #{chunk.rank} · {chunk.filename}
                            {chunk.page ? ` · Page ${chunk.page}` : ""}
                          </strong>
                          <small>Score {chunk.score?.toFixed(4)}</small>
                        </div>
                        <p>{chunk.content}</p>
                        <small>Citation / chunk: {chunk.citation_id}</small>
                      </article>
                    ))
                  )}
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
