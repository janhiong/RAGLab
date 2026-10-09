"use client";
import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "../lib/api";
type Dataset = {
  id: string;
  name: string;
  reviewed: boolean;
  question_count: number;
};
type Metrics = {
  attempted: number;
  failed: number;
  recall_at_k: number | null;
  mrr: number | null;
  failure_rate: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  correctness: number | null;
  faithfulness: number | null;
  manually_reviewed_count: number;
};
type Run = {
  id: string;
  name: string;
  status: string;
  processed?: number;
  total?: number;
  configuration: { dataset_reviewed?: boolean; mode?: string; split?: string };
  aggregate_metrics: Metrics | null;
  error?: string | null;
};
type Result = {
  question_id: string;
  status: string;
  question: { question: string; reference_answer: string; category: string };
  metrics: { recall_at_k: number | null; reciprocal_rank: number | null };
  elapsed_ms: number;
  error: unknown;
  answer: { answer: string } | null;
  retrieval: {
    items: { id: string; filename: string; content: string }[];
  } | null;
  review: unknown;
};
const measured = (value: number | null | undefined) =>
  value == null ? "Not measured" : value.toFixed(3);
export default function EvaluationWorkspace() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [dataset, setDataset] = useState("");
  const [selected, setSelected] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [results, setResults] = useState<Result[]>([]);
  const [strategy, setStrategy] = useState("keyword");
  const [split, setSplit] = useState("development");
  const [mode, setMode] = useState("retrieval");
  const [model, setModel] = useState("");
  const [topK, setTopK] = useState(5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [writable, setWritable] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const [data, history, caps] = await Promise.all([
        apiRequest<{ items: Dataset[] }>("/datasets"),
        apiRequest<{ items: Run[] }>("/experiments"),
        apiRequest<{ private_uploads_enabled: boolean }>("/capabilities"),
      ]);
      setDatasets(data.items);
      setRuns(history.items.filter((item) => item.configuration));
      setWritable(caps.private_uploads_enabled);
      setDataset((current) =>
        data.items.some((item) => item.id === current)
          ? current
          : (data.items[0]?.id ?? ""),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Evaluation unavailable");
    }
  }, []);
  const detail = useCallback(async (id: string) => {
    if (!id) return;
    try {
      const [r, rows] = await Promise.all([
        apiRequest<Run>(`/experiments/${id}`),
        apiRequest<{ items: Result[] }>(`/experiments/${id}/results?limit=100`),
      ]);
      setRun(r);
      setResults(rows.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Run unavailable");
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    setRun(null);
    setResults([]);
    void detail(selected);
  }, [selected, detail]);
  useEffect(() => {
    if (!run || !["queued", "running"].includes(run.status)) return;
    const timer = setInterval(() => {
      void detail(run.id);
    }, 3000);
    return () => clearInterval(timer);
  }, [run, detail]);
  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await apiRequest<{ id: string }>("/experiments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: `${strategy} · ${split}`,
          dataset_id: dataset,
          strategy,
          top_k: topK,
          split,
          mode,
          model: mode === "generation" ? model : null,
        }),
      });
      await refresh();
      setSelected(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not queue run");
    } finally {
      setBusy(false);
    }
  }
  async function cancel() {
    if (!run) return;
    try {
      await apiRequest(`/experiments/${run.id}/cancel`, { method: "POST" });
      await detail(run.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancellation failed");
    }
  }
  async function review(event: React.FormEvent<HTMLFormElement>, row: Result) {
    event.preventDefault();
    if (!run) return;
    const data = new FormData(event.currentTarget);
    try {
      await apiRequest(
        `/experiments/${run.id}/results/${encodeURIComponent(row.question_id)}/review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            correctness: Number(data.get("correctness")),
            faithfulness: Number(data.get("faithfulness")),
            rationale: data.get("rationale"),
          }),
        },
      );
      await detail(run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Review failed");
    }
  }
  const metrics = run?.aggregate_metrics;
  return (
    <section id="evaluation">
      <div className="section-heading">
        <div>
          <span className="eyebrow">REPRODUCIBLE EVALUATION</span>
          <h2>Measure a run</h2>
        </div>
        <button
          onClick={() => {
            setError(null);
            void refresh();
            if (selected) void detail(selected);
          }}
        >
          Refresh evaluation
        </button>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {datasets.length === 0 ? (
        <p className="notice">
          No datasets yet. Import the quote-anchored starter dataset using the
          README instructions.
        </p>
      ) : (
        writable && (
          <form className="search-form" onSubmit={create}>
            <div className="search-options">
              <label>
                Evaluation dataset
                <select
                  value={dataset}
                  onChange={(event) => {
                    setDataset(event.target.value);
                    setSplit("development");
                  }}
                >
                  {datasets.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} · {item.question_count} questions ·{" "}
                      {item.reviewed ? "reviewed" : "draft labels"}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Evaluation strategy
                <select
                  value={strategy}
                  onChange={(event) => setStrategy(event.target.value)}
                >
                  <option value="keyword">PostgreSQL full-text</option>
                  <option value="vector">Vector</option>
                  <option value="hybrid">Hybrid RRF</option>
                </select>
              </label>
              <label>
                Dataset split
                <select
                  value={split}
                  onChange={(event) => setSplit(event.target.value)}
                >
                  <option value="development">Development</option>
                  <option
                    value="holdout"
                    disabled={
                      !datasets.find((item) => item.id === dataset)?.reviewed
                    }
                  >
                    Holdout (reviewed labels)
                  </option>
                </select>
              </label>
              <label>
                Evaluation mode
                <select
                  value={mode}
                  onChange={(event) => setMode(event.target.value)}
                >
                  <option value="retrieval">Retrieval only</option>
                  <option value="generation">Retrieval + generation</option>
                </select>
              </label>
              <label>
                Evaluation top K
                <input
                  type="number"
                  value={topK}
                  min={1}
                  max={20}
                  required
                  onChange={(event) => setTopK(Number(event.target.value))}
                />
              </label>
            </div>
            {mode === "generation" && (
              <label>
                Evaluation model
                <input
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  required
                  placeholder="qwen2.5:1.5b"
                />
              </label>
            )}
            <button disabled={busy} type="submit">
              Queue experiment
            </button>
            <p className="muted">
              The CLI worker processes the queue and saves progress. Start it
              using the README instructions.
            </p>
          </form>
        )
      )}
      <label>
        Inspect experiment
        <select
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
        >
          <option value="">Select a run</option>
          {runs.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} · {item.status}
            </option>
          ))}
        </select>
      </label>
      {run && (
        <>
          <div className="section-heading">
            <p>
              {run.status} · {run.processed ?? 0}/{run.total ?? 0} questions
              processed
            </p>
            {writable && ["queued", "running"].includes(run.status) && (
              <button onClick={() => void cancel()}>Cancel run</button>
            )}
          </div>
          {!run.configuration.dataset_reviewed && (
            <p className="notice">
              Draft labels: provisional development measurements. Human review
              is required before holdout evaluation.
            </p>
          )}
          {run.error && <p className="error">{run.error}</p>}
          <div className="metrics">
            <article>
              <p>RECALL@K / MRR</p>
              <strong className="unmeasured">
                {measured(metrics?.recall_at_k)} / {measured(metrics?.mrr)}
              </strong>
              <small>Answerable questions only</small>
            </article>
            <article>
              <p>FAILED ATTEMPTS</p>
              <strong>{metrics?.failed ?? "—"}</strong>
              <small>Retained in denominators</small>
            </article>
            <article>
              <p>TOTAL LATENCY P50 / P95</p>
              <strong className="unmeasured">
                {measured(metrics?.latency_p50_ms)} /{" "}
                {measured(metrics?.latency_p95_ms)}
              </strong>
              <small>Milliseconds, including failed attempts</small>
            </article>
          </div>
          <p className="muted">
            Correctness {measured(metrics?.correctness)} · Faithfulness{" "}
            {measured(metrics?.faithfulness)} ·{" "}
            {metrics?.manually_reviewed_count ?? 0} manually reviewed answers
            (0–2 rubric)
          </p>
          {results.length === 0 ? (
            <p>No question results yet.</p>
          ) : (
            results.map((row) => (
              <details key={row.question_id} className="source-chunk">
                <summary>
                  {row.question_id} · {row.status} · {row.question.question}
                </summary>
                <p>Reference: {row.question.reference_answer}</p>
                <p>
                  Recall {measured(row.metrics.recall_at_k)} · Reciprocal rank{" "}
                  {measured(row.metrics.reciprocal_rank)} ·{" "}
                  {row.elapsed_ms.toFixed(1)} ms
                </p>
                {row.answer && <p>Generated answer: {row.answer.answer}</p>}
                {row.error != null && (
                  <pre className="evaluation-error">
                    {JSON.stringify(row.error, null, 2)}
                  </pre>
                )}
                {row.retrieval?.items.map((item) => (
                  <article key={item.id}>
                    <small>
                      {item.filename} · {item.id}
                    </small>
                    <p>{item.content}</p>
                  </article>
                ))}
                {writable &&
                  row.answer &&
                  row.status === "completed" &&
                  !["queued", "running"].includes(run.status) && (
                    <form onSubmit={(event) => void review(event, row)}>
                      <label>
                        Correctness score
                        <select name="correctness">
                          <option value="0">0 — incorrect</option>
                          <option value="1">1 — partial</option>
                          <option value="2">2 — correct</option>
                        </select>
                      </label>
                      <label>
                        Faithfulness score
                        <select name="faithfulness">
                          <option value="0">0 — unsupported</option>
                          <option value="1">1 — mixed</option>
                          <option value="2">2 — supported</option>
                        </select>
                      </label>
                      <label>
                        Review rationale
                        <textarea name="rationale" required maxLength={3000} />
                      </label>
                      <button type="submit">Save manual review</button>
                      {row.review != null && <p>Manual review saved.</p>}
                    </form>
                  )}
              </details>
            ))
          )}
          <small>
            Showing first 100 results; the API and export support larger
            datasets.
          </small>
        </>
      )}
    </section>
  );
}
