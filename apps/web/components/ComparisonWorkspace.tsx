"use client";
import { useEffect, useState } from "react";
import { apiRequest, type Experiment } from "../lib/api";

type Result = {
  status: string;
  retrieval: { items: { id: string; content: string }[] } | null;
  answer: {
    answer: string;
    input_sha256?: string;
    model_digest?: string;
  } | null;
  error: unknown;
};
type Pair = {
  question: { id: string; question: string; reference_answer: string };
  baseline: Result | null;
  candidate: Result | null;
  baseline_failures: string[];
  candidate_failures: string[];
};
type Comparison = {
  metrics: Record<string, number | null>[];
  deltas: Record<string, number | null>;
  complete_coverage: boolean;
  controlled_context: boolean;
  reviewed_labels: boolean;
  total: number;
  questions: Pair[];
  baseline: { configuration: unknown };
  candidate: { configuration: unknown };
};
const metricNames = [
  "attempted",
  "failed",
  "recall_at_k",
  "mrr",
  "failure_rate",
  "latency_p50_ms",
  "latency_p95_ms",
  "correctness",
  "faithfulness",
  "manually_reviewed_count",
];

export default function ComparisonWorkspace() {
  const [runs, setRuns] = useState<Experiment[]>([]);
  const [baseline, setBaseline] = useState("");
  const [candidate, setCandidate] = useState("");
  const [data, setData] = useState<Comparison | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("all");
  const [models, setModels] = useState<string[]>([]);
  const [modelA, setModelA] = useState("");
  const [modelB, setModelB] = useState("");
  const [writable, setWritable] = useState(false);
  const [generation, setGeneration] = useState(false);
  const [message, setMessage] = useState("");
  async function refresh() {
    try {
      const [history, caps] = await Promise.all([
        apiRequest<{ items: Experiment[] }>("/experiments"),
        apiRequest<{
          private_uploads_enabled: boolean;
          generation: { available: boolean; models: { name: string }[] };
        }>("/capabilities"),
      ]);
      setRuns(history.items);
      setWritable(caps.private_uploads_enabled);
      setGeneration(caps.generation.available);
      setModels(caps.generation.models.map((m) => m.name));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load experiments.");
    }
  }
  useEffect(() => {
    void refresh();
  }, []);
  async function compare() {
    setBusy(true);
    setData(null);
    setError("");
    try {
      setData(
        await apiRequest<Comparison>(
          `/comparisons?baseline=${baseline}&candidate=${candidate}`,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Comparison failed.");
    } finally {
      setBusy(false);
    }
  }
  async function queue() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await apiRequest<{
        runs: { id: string }[];
        context_sha256: string;
      }>("/model-comparisons", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_run_id: baseline,
          models: [modelA, modelB],
        }),
      });
      setMessage(
        `Queued two runs. Run the evaluation worker, then refresh and compare. Context SHA256: ${result.context_sha256}`,
      );
      setBaseline(result.runs[0].id);
      setCandidate(result.runs[1].id);
      setData(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to queue comparison.");
    } finally {
      setBusy(false);
    }
  }
  const options = runs.map((run) => (
    <option key={run.id} value={run.id}>
      {run.name} · {run.status}
    </option>
  ));
  return (
    <section id="comparison">
      <div className="section-heading">
        <div>
          <span className="eyebrow">MEASURE → DIAGNOSE</span>
          <h2>Compare experiments</h2>
        </div>
        <button onClick={() => void refresh()} disabled={busy}>
          Refresh runs
        </button>
      </div>
      <p>
        Choose terminal runs using the same dataset, corpus version, split, and
        evaluation mode. Deltas are withheld if either run has missing attempts.
        Unmeasured scores remain blank.
      </p>
      <div className="form-grid">
        <label>
          Baseline
          <select
            value={baseline}
            onChange={(e) => {
              setBaseline(e.target.value);
              setData(null);
            }}
          >
            <option value="">Select run</option>
            {options}
          </select>
        </label>
        <label>
          Candidate
          <select
            value={candidate}
            onChange={(e) => {
              setCandidate(e.target.value);
              setData(null);
            }}
          >
            <option value="">Select run</option>
            {options}
          </select>
        </label>
      </div>
      <button
        onClick={() => void compare()}
        disabled={busy || !baseline || !candidate || baseline === candidate}
      >
        Compare runs
      </button>
      <details>
        <summary>Queue two local models with identical saved context</summary>
        <p>
          Select a completed retrieval run as the baseline above. Both queued
          model runs reuse its saved source ordering, prompt, and output budget.
          Start the evaluation worker to execute them.
        </p>
        <label>
          Model A
          <select value={modelA} onChange={(e) => setModelA(e.target.value)}>
            <option value="">Select model</option>
            {models.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <label>
          Model B
          <select value={modelB} onChange={(e) => setModelB(e.target.value)}>
            <option value="">Select model</option>
            {models.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <button
          onClick={() => void queue()}
          disabled={
            busy ||
            !writable ||
            !generation ||
            !baseline ||
            !modelA ||
            !modelB ||
            modelA === modelB
          }
        >
          Queue model comparison
        </button>
        {!generation && (
          <p>
            Live generation is disabled. Saved retrieval comparisons remain
            available.
          </p>
        )}
      </details>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {data && (
        <>
          <p className="notice">
            {data.reviewed_labels
              ? "Reviewed labels"
              : "Draft labels · provisional results"}{" "}
            · {data.total} questions ·{" "}
            {data.complete_coverage
              ? "Complete attempt coverage"
              : "Incomplete coverage · no deltas"}{" "}
            ·{" "}
            {data.controlled_context
              ? "Identical frozen context and generation settings"
              : "General experiment comparison"}
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Baseline</th>
                  <th>Candidate</th>
                  <th>Candidate − baseline</th>
                </tr>
              </thead>
              <tbody>
                {metricNames.map((key) => (
                  <tr key={key}>
                    <td>{key.replaceAll("_", " ")}</td>
                    {[
                      data.metrics[0][key],
                      data.metrics[1][key],
                      data.deltas[key],
                    ].map((value, i) => (
                      <td key={i}>
                        {value == null ? "—" : Number(value.toFixed(4))}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary>Recorded configurations</summary>
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
              {JSON.stringify(
                {
                  baseline: data.baseline.configuration,
                  candidate: data.candidate.configuration,
                },
                null,
                2,
              )}
            </pre>
          </details>
          <h3>Failure analysis</h3>
          <label>
            Show
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              {[
                "all",
                "retrieval_miss",
                "request_failure",
                "not_attempted",
                "answerable_abstention",
                "unsupported_answer",
                "manual_review_issue",
              ].map((value) => (
                <option key={value} value={value}>
                  {value.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </label>
          {data.questions
            .filter(
              (pair) =>
                filter === "all" ||
                [
                  ...pair.baseline_failures,
                  ...pair.candidate_failures,
                ].includes(filter),
            )
            .map((pair) => (
              <details key={pair.question.id}>
                <summary>
                  {pair.question.id} · {pair.question.question}
                </summary>
                <p>Reference: {pair.question.reference_answer}</p>
                {[pair.baseline, pair.candidate].map((result, i) => (
                  <div key={i}>
                    <h4>{i === 0 ? "Baseline" : "Candidate"}</h4>
                    <p>
                      {(i === 0
                        ? pair.baseline_failures
                        : pair.candidate_failures
                      ).join(", ") || "No detected failure"}
                    </p>
                    <p>{result?.answer?.answer || "No generated answer"}</p>
                    {result?.error != null && (
                      <pre style={{ whiteSpace: "pre-wrap" }}>
                        {JSON.stringify(result.error, null, 2)}
                      </pre>
                    )}
                    {result?.retrieval?.items.map((item) => (
                      <blockquote key={item.id}>{item.content}</blockquote>
                    ))}
                    {result?.answer?.input_sha256 && (
                      <small>
                        Input SHA256: {result.answer.input_sha256} · model
                        digest: {result.answer.model_digest}
                      </small>
                    )}
                  </div>
                ))}
              </details>
            ))}
          <p>
            Failure tags identify observable symptoms. Citation membership alone
            does not establish faithfulness; answer quality requires manual
            review in Evaluation.
          </p>
        </>
      )}
    </section>
  );
}
