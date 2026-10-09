"use client";
import { useCallback, useEffect, useState } from "react";
import { request, type Overview, type Experiment } from "../lib/api";
import CorpusWorkspace from "../components/CorpusWorkspace";
import RAGPlayground from "../components/RAGPlayground";
import EvaluationWorkspace from "../components/EvaluationWorkspace";

export default function Dashboard() {
  const [data, setData] = useState<Overview | null>(null);
  const [runs, setRuns] = useState<Experiment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const [overview, history] = await Promise.all([
        request<Overview>("/overview", signal),
        request<{ items: Experiment[] }>("/experiments", signal),
      ]);
      setData(overview);
      setRuns(history.items);
    } catch (err) {
      if (signal?.aborted) return;
      setData(null);
      setRuns([]);
      setError(err instanceof Error ? err.message : "Unable to load results.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  return (
    <div className="shell">
      <aside>
        <a className="brand" href="/">
          RAG<span>LAB</span>
        </a>
        <p className="sidebar-label">EXPERIMENT WORKSPACE</p>
        <nav>
          <a href="#overview">Overview</a>
          <a href="#documents">Documents & search</a>
          <a href="#playground">Playground</a>
          <a href="#evaluation">Evaluation</a>
          <a href="#experiments">Experiments</a>
          <a href="#roadmap">Roadmap</a>
        </nav>
        <div className="sidebar-note">
          Local-first research
          <br />
          <small>No paid APIs required</small>
        </div>
      </aside>
      <main id="overview">
        <header>
          <span className="eyebrow">BUILD → MEASURE → IMPROVE</span>
          <span className="badge">Grounded RAG playground</span>
        </header>
        <h1>
          Make your retrieval
          <br />
          <span>measurable.</span>
        </h1>
        <p className="intro">
          A workspace for comparing retrieval strategies, inspecting evidence,
          and understanding why a RAG system succeeds or fails.
        </p>
        <div className="notice">
          {data?.live_generation
            ? "Local generation is available in the playground. Review each answer against its source excerpts."
            : "Live generation is unavailable. Start Ollama and enable generation to use the playground; source search remains available."}{" "}
          Benchmark metrics remain unmeasured.
        </div>
        {error && (
          <div className="error" role="alert">
            {error}{" "}
            <button onClick={() => void load()} disabled={loading}>
              Retry
            </button>
          </div>
        )}
        <div className="metrics" aria-live="polite">
          <article>
            <p>DOCUMENTS</p>
            <strong>{loading ? "…" : (data?.documents ?? "—")}</strong>
            <small>Indexed corpus inventory</small>
          </article>
          <article>
            <p>EXPERIMENT RUNS</p>
            <strong>{loading ? "…" : (data?.experiments ?? "—")}</strong>
            <small>Persisted experiment history</small>
          </article>
          <article>
            <p>RETRIEVAL QUALITY</p>
            <strong className="unmeasured">Not measured</strong>
            <small>Recall@K and MRR</small>
          </article>
        </div>
        <CorpusWorkspace onChange={() => void load()} />
        <RAGPlayground />
        <EvaluationWorkspace />
        <section id="experiments">
          <div className="section-heading">
            <div>
              <span className="eyebrow">BENCHMARK HISTORY</span>
              <h2>Your experiments</h2>
            </div>
            <button onClick={() => void load()} disabled={loading}>
              {loading ? "Loading…" : "Refresh"}
            </button>
          </div>
          {loading ? (
            <p role="status">Loading experiment history…</p>
          ) : error ? (
            <p>
              Experiment history is unavailable while the API is disconnected.
            </p>
          ) : runs.length === 0 ? (
            <div className="empty">
              <span className="empty-icon">↗</span>
              <h3>No experiments yet</h3>
              <p>
                Measured results will appear here after the experiment runner is
                implemented and a benchmark completes.
              </p>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Experiment</th>
                    <th>Status</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.id}>
                      <td>{run.name}</td>
                      <td>{run.status}</td>
                      <td>{new Date(run.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <section id="roadmap">
          <span className="eyebrow">NEXT MILESTONES</span>
          <h2>From documents to evidence</h2>
          <div className="roadmap">
            <article>
              <span>01</span>
              <h3>Build a labeled dataset</h3>
              <p>
                Create answerable and unanswerable questions with verified
                source labels.
              </p>
            </article>
            <article>
              <span>02</span>
              <h3>Evaluate retrieval</h3>
              <p>Label a dataset and measure Recall@K, MRR, and latency.</p>
            </article>
            <article>
              <span>03</span>
              <h3>Compare models</h3>
              <p>
                Compare local models on identical context and inspect failures.
              </p>
            </article>
          </div>
        </section>
        <footer>RAG Lab · Results are shown only after measurement.</footer>
      </main>
    </div>
  );
}
