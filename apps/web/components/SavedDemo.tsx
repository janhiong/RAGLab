"use client";
import { useState } from "react";
import saved from "../../../benchmarks/keyword-any-term-comparison-draft.json";
const metricKeys = [
  "recall_at_k",
  "mrr",
  "attempted",
  "failed",
  "latency_p50_ms",
  "latency_p95_ms",
  "correctness",
  "faithfulness",
] as const;
const format = (value: unknown) =>
  typeof value === "number" ? String(Number(value.toFixed(4))) : "Not measured";
const repository = "https://github.com/janhiong/RAGLab";
export default function SavedDemo() {
  const [filter, setFilter] = useState("all");
  const [text, setText] = useState("");
  const questions = saved.questions.filter(
    (pair) =>
      (filter === "all" ||
        (filter === "misses" &&
          pair.baseline_failures.some((tag) => tag === "retrieval_miss")) ||
        (filter === "unanswerable" && !pair.question.answerable)) &&
      `${pair.question.id} ${pair.question.question}`
        .toLowerCase()
        .includes(text.toLowerCase()),
  );
  return (
    <div className="shell">
      <aside>
        <a className="brand" href="#top">
          RAG<span>LAB</span>
        </a>
        <p className="sidebar-label">SAVED BENCHMARK DEMO</p>
        <nav>
          <a href="#comparison">Comparison</a>
          <a href="#failures">Failure analysis</a>
          <a href="#method">Method & limits</a>
          <a href={repository}>GitHub ↗</a>
        </nav>
        <div className="sidebar-note">
          Read-only portfolio
          <br />
          <small>Original CC0 sample corpus</small>
        </div>
      </aside>
      <main id="top">
        <header>
          <span className="eyebrow">BUILD → MEASURE → IMPROVE</span>
          <span className="badge">Saved results · read-only</span>
        </header>
        <h1>
          Inspect the evidence.
          <br />
          <span>Understand the change.</span>
        </h1>
        <p className="intro">
          Compare two measured keyword retrieval runs, inspect the exact source
          excerpts, and see which questions the change recovered.
        </p>
        <div className="notice">
          <strong>Saved benchmark results · draft labels.</strong> Live
          generation is unavailable in this demo. No uploads, live queries, or
          new experiments are enabled. These are development measurements on a
          two-chunk sample, not validated holdout results.
        </div>
        <div className="metrics">
          <article>
            <p>RECALL@3 · BASELINE → CANDIDATE</p>
            <strong>
              {format(saved.metrics[0].recall_at_k)} →{" "}
              {format(saved.metrics[1].recall_at_k)}
            </strong>
            <small>19 answerable development questions</small>
          </article>
          <article>
            <p>QUESTIONS ATTEMPTED</p>
            <strong>{saved.total}</strong>
            <small>19 answerable · 5 unanswerable · no failed requests</small>
          </article>
          <article>
            <p>MODEL ANSWER QUALITY</p>
            <strong className="unmeasured">Not measured</strong>
            <small>Retrieval-only runs; no generated answers</small>
          </article>
        </div>
        <section id="comparison">
          <span className="eyebrow">ONE CONFIGURATION CHANGE</span>
          <h2>Web search → any-term matching</h2>
          <p className="muted">
            Same corpus, draft dataset version, development split, keyword
            ranker, and top-K 3. The baseline requires ordinary query terms
            together; the candidate matches any English query lexeme.
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
                {metricKeys.map((key) => (
                  <tr key={key}>
                    <th scope="row">{key.replaceAll("_", " ")}</th>
                    <td>{format(saved.metrics[0][key])}</td>
                    <td>{format(saved.metrics[1][key])}</td>
                    <td>{format(saved.deltas[key])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            Broader matching recovered eight misses, but ranked the relevant
            chunk second for two questions. The observed p95 increased; separate
            single runs do not establish a stable latency regression.
          </p>
          <details>
            <summary>Run provenance and configurations</summary>
            <p className="muted">
              Baseline: {saved.baseline.id}
              <br />
              Candidate: {saved.candidate.id}
              <br />
              Dataset version: {saved.baseline.dataset_version}
              <br />
              Corpus version: {saved.baseline.corpus_version}
            </p>
            <pre className="demo-code">
              {JSON.stringify(
                {
                  baseline: saved.baseline.configuration,
                  candidate: saved.candidate.configuration,
                },
                null,
                2,
              )}
            </pre>
          </details>
        </section>
        <section id="failures">
          <span className="eyebrow">PAIRED QUESTION INSPECTION</span>
          <h2>Failure analysis</h2>
          <label htmlFor="demo-search">Find a question</label>
          <input
            id="demo-search"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Question text or ID"
          />
          <label htmlFor="demo-filter">Show questions</label>
          <select
            id="demo-filter"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">All questions</option>
            <option value="misses">Baseline retrieval misses</option>
            <option value="unanswerable">Unanswerable questions</option>
          </select>
          <p role="status">
            {questions.length} of {saved.total} questions shown
          </p>
          {questions.length === 0 && (
            <p>No matching questions. Clear the search or change the filter.</p>
          )}
          {questions.map((pair) => (
            <details key={pair.question.id}>
              <summary>
                {pair.question.id} · {pair.question.question}
              </summary>
              <p>
                <strong>Reference answer:</strong>{" "}
                {pair.question.reference_answer}
              </p>
              <p className="muted">
                {pair.question.answerable ? "Answerable" : "Unanswerable"} ·{" "}
                {pair.question.category} · development split
              </p>
              {[pair.baseline, pair.candidate].map((result, i) => (
                <article className="source-chunk" key={i}>
                  <h3>{i === 0 ? "Baseline" : "Candidate"} · saved result</h3>
                  <p>
                    Recall@3: {format(result.metrics.recall_at_k)} · Reciprocal
                    rank: {format(result.metrics.reciprocal_rank)}
                  </p>
                  <p>
                    {(i === 0
                      ? pair.baseline_failures
                      : pair.candidate_failures
                    ).join(", ") || "No detected retrieval failure"}
                  </p>
                  {result.retrieval.items.length === 0 && (
                    <p>No source chunks retrieved.</p>
                  )}
                  {result.retrieval.items.map((item) => (
                    <details key={item.id}>
                      <summary>
                        Rank {item.rank} · {item.filename} ·{" "}
                        {item.page ? `page ${item.page}` : "no page number"}
                      </summary>
                      <small>
                        Chunk ID: {item.id} · score: {item.score}
                      </small>
                      <p>{item.content}</p>
                    </details>
                  ))}
                  <p className="muted">
                    No generated answer: this was a retrieval-only experiment.
                  </p>
                </article>
              ))}
            </details>
          ))}
        </section>
        <section id="method">
          <h2>What these results establish</h2>
          <p className="muted">
            The benchmark measures lexical retrieval against saved source labels
            on one original CC0 document. Draft labels have not received human
            review. Coarse chunks and the small sample limit generalization.
            Unanswerable questions are excluded from Recall/MRR; abstention,
            correctness, and faithfulness remain unmeasured.
          </p>
          <p className="muted">
            The local workspace also supports vector/hybrid retrieval and
            two-model comparisons using identical frozen context. Real model
            weights were unavailable in the build environment, so no
            model-quality claims are made.
          </p>
          <p>
            <a href={`${repository}/blob/main/docs/comparison.md`}>
              Case study ↗
            </a>{" "}
            ·{" "}
            <a href={`${repository}/blob/main/docs/architecture.md`}>
              Architecture ↗
            </a>{" "}
            ·{" "}
            <a
              href={`${repository}/blob/main/benchmarks/keyword-any-term-comparison-draft.json`}
            >
              Full benchmark export ↗
            </a>
          </p>
        </section>
        <footer>
          RAG Lab · Saved measurements, visible limitations, reproducible code.
        </footer>
      </main>
    </div>
  );
}
