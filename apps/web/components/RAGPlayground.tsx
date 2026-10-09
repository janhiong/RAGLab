"use client";

import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "../lib/api";

type Document = {
  id: string;
  filename: string;
  embedding_version: string | null;
};
type Generation = {
  available: boolean;
  reason: string | null;
  models: { name: string; digest: string }[];
};
type Source = {
  citation_id: string;
  chunk_id: string;
  filename: string;
  page: number | null;
  content: string;
};
type Answer = {
  trace_id: string;
  answer: string;
  abstained: boolean;
  citations: Source[];
  model: string | null;
  model_digest: string | null;
  generation_performed: boolean;
  retrieval_ms: number;
  generation_ms: number;
  token_usage: { prompt_eval_count: number | null; eval_count: number | null };
};

export default function RAGPlayground() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [generation, setGeneration] = useState<Generation | null>(null);
  const [documentId, setDocumentId] = useState("");
  const [model, setModel] = useState("");
  const [question, setQuestion] = useState("");
  const [strategy, setStrategy] = useState("keyword");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      const [docs, caps] = await Promise.all([
        apiRequest<{ items: Document[] }>("/documents?limit=100"),
        apiRequest<{ generation: Generation }>("/capabilities"),
      ]);
      setDocuments(docs.items);
      setGeneration(caps.generation);
      setDocumentId((current) =>
        docs.items.some((doc) => doc.id === current)
          ? current
          : (docs.items[0]?.id ?? ""),
      );
      setModel((current) =>
        caps.generation.models.some((item) => item.name === current)
          ? current
          : (caps.generation.models[0]?.name ?? ""),
      );
      setStrategy("keyword");
    } catch (err) {
      setGeneration(null);
      setError(
        err instanceof Error ? err.message : "Could not load the playground.",
      );
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  const document = documents.find((doc) => doc.id === documentId);
  async function generate(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setAnswer(null);
    try {
      setAnswer(
        await apiRequest<Answer>("/query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question,
            document_id: documentId,
            model,
            strategy,
            top_k: 3,
          }),
        }),
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Answer generation failed.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section id="playground">
      <div className="section-heading">
        <div>
          <span className="eyebrow">GROUNDED GENERATION</span>
          <h2>RAG Playground</h2>
        </div>
        <button onClick={() => void refresh()} disabled={loading || busy}>
          Refresh playground
        </button>
      </div>
      <p className="muted">
        Ask a question against one document using a local Ollama model. Source
        references are checked; factual support still needs review.
      </p>
      {loading ? (
        <p role="status">Checking local generation…</p>
      ) : !generation?.available ? (
        <div className="notice" role="status">
          {generation?.reason ?? "Generation status is unavailable."}{" "}
          Retrieval-only search remains available above.
        </div>
      ) : (
        <p className="generation-ready">
          Local generation ready · {generation.models.length} installed model(s)
        </p>
      )}
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <form className="search-form" onSubmit={generate}>
        <div className="search-options">
          <label>
            Playground document
            <select
              value={documentId}
              onChange={(event) => {
                setDocumentId(event.target.value);
                setStrategy("keyword");
                setAnswer(null);
              }}
              disabled={busy || loading || documents.length === 0}
              required
            >
              <option value="" disabled>
                Select a document
              </option>
              {documents.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.filename}
                </option>
              ))}
            </select>
          </label>
          <label>
            Local model
            <select
              value={model}
              onChange={(event) => {
                setModel(event.target.value);
                setAnswer(null);
              }}
              disabled={busy || loading || !generation?.available}
              required
            >
              <option value="" disabled>
                No installed model
              </option>
              {generation?.models.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Answer retrieval
            <select
              value={strategy}
              disabled={busy}
              onChange={(event) => {
                setStrategy(event.target.value);
                setAnswer(null);
              }}
            >
              <option value="keyword">PostgreSQL full-text</option>
              <option value="vector" disabled={!document?.embedding_version}>
                Vector
              </option>
              <option value="hybrid" disabled={!document?.embedding_version}>
                Hybrid RRF
              </option>
            </select>
          </label>
        </div>
        <label htmlFor="rag-question">Ask a question</label>
        <textarea
          id="rag-question"
          value={question}
          onChange={(event) => {
            setQuestion(event.target.value);
            setAnswer(null);
          }}
          required
          maxLength={2000}
          disabled={busy}
          placeholder="What is cosine similarity?"
        />
        <button
          type="submit"
          disabled={
            busy ||
            loading ||
            !generation?.available ||
            !model ||
            !documentId ||
            !question.trim()
          }
        >
          {busy ? "Generating…" : "Generate answer"}
        </button>
        {busy && (
          <p role="status">
            Retrieving sources and waiting for the local model. CPU generation
            may take a minute.
          </p>
        )}
      </form>
      {answer && (
        <div className="generated-answer" aria-live="polite">
          <div className="section-heading">
            <h3>
              {answer.abstained ? "Insufficient evidence" : "Generated answer"}
            </h3>
            <small>
              {answer.generation_performed
                ? "New local model response"
                : "No-evidence abstention · model not called"}
            </small>
          </div>
          <p className="answer-text">
            {answer.answer.split(/(\[S\d+\])/).map((part, index) =>
              /^\[S\d+\]$/.test(part) ? (
                <a key={index} href={`#query-source-${part.slice(1, -1)}`}>
                  {part}
                </a>
              ) : (
                part
              ),
            )}
          </p>
          <p className="muted">
            Retrieval {answer.retrieval_ms.toFixed(1)} ms · Generation{" "}
            {answer.generation_ms.toFixed(1)} ms · Output tokens{" "}
            {answer.token_usage.eval_count ?? "Not reported"}
          </p>
          {answer.citations.map((source) => (
            <article
              className="source-chunk"
              id={`query-source-${source.citation_id}`}
              key={source.citation_id}
            >
              <strong>
                {source.citation_id} · {source.filename}
                {source.page ? ` · Page ${source.page}` : ""}
              </strong>
              <p>{source.content}</p>
              <small>Source chunk {source.chunk_id}</small>
            </article>
          ))}
          <details>
            <summary>Query trace and model provenance</summary>
            <p className="muted">
              Trace {answer.trace_id}
              <br />
              Model {answer.model ?? "Not called"}
              <br />
              Digest {answer.model_digest ?? "Not applicable"}
            </p>
          </details>
        </div>
      )}
    </section>
  );
}
