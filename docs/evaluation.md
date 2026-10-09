# Evaluation methodology

Milestone 4 supports durable sequential experiment runs against one document. Retrieval-only runs need PostgreSQL, not an LLM. Generation runs use the milestone 3 Ollama integration and persist its traces; they remain dependent on a working local model.

## Starter dataset and review

`datasets/retrieval-notes-draft.json` contains 32 authored questions: 25 answerable and 7 unanswerable. Eight are assigned to holdout and 24 to development. Questions are grounded with literal source quotes; import resolves those quotes into the indexed chunk IDs. An unresolved quote or duplicate question ID is rejected. Dataset versions hash the resolved questions, corpus version, and review status.

**The starter labels are drafts, not human-validated ground truth.** Review question wording, reference answers, answerability, all relevant chunks, and split membership against the original sample. Quote matches check location, not label completeness. After manual review, set `reviewed: true` in a separately saved dataset file and import it to create a new immutable version. Do not tune against the holdout results. The API blocks holdout runs on unreviewed datasets.

The tiny sample has only two overlapping chunks, and many questions are related paraphrases. Development results are diagnostic only; they are not evidence of broad RAG quality. Human review may change labels and the resulting measurements. Dataset expansion and locked holdout measurements are future validation work.

## Metrics and denominators

- Recall@K: number of unique relevant retrieved chunks / all labeled relevant chunks. With one relevant chunk this is hit rate.
- Reciprocal rank: inverse rank of the first relevant chunk, zero when no relevant chunk is retrieved. MRR averages this across attempted answerable questions.
- Unanswerable questions have null Recall/RR and are excluded from these two denominators.
- Failed attempts remain in failure-rate and answerable retrieval denominators. Missing retrieval contributes zero; if retrieval succeeded before generation failed, its actual retrieval measurements are retained.
- Abstention accuracy is measured only for unanswerable generation-mode attempts, including failures as incorrect. It measures the full pipeline, including the deterministic no-evidence fallback. `no_evidence_abstentions` identifies that fallback; it must not be described as evidence of LLM abstention quality. Retrieval-only runs do not measure abstention.
- Total latency includes failed attempts and per-question processing; p50/p95 use linear interpolation over observed timings. Retrieval and generation timings are also aggregated separately when available. Interrupted attempts have an unknown duration currently stored as zero; exclude interrupted runs from performance claims.
- Correctness and faithfulness remain null until manual scores exist. Means include only manually reviewed answers, with the reviewed count reported; unreviewed answers never become automatic passing grades. There is no keyword-overlap correctness score or authoritative automated judge.

## Manual review rubric

Review a completed generated answer against its reference and the exact saved context. Score correctness and faithfulness independently:

| Score | Correctness | Faithfulness |
|---|---|---|
| 0 | Incorrect or fails the question | Unsupported claims |
| 1 | Partially correct or incomplete | Mix of supported and unsupported claims |
| 2 | Correct and sufficiently complete | Claims supported by the supplied sources |

Record a rationale. Valid citation IDs alone do not justify a faithfulness score. These are manual annotations, not independent guarantees. The API permits reviews only for terminal runs and successful answer results. A later review replaces that question's prior score; immutable review-history auditing is future work.

## Worker lifecycle

The API queues runs; it does not perform benchmark work in request handlers. A CLI worker obtains a PostgreSQL advisory lock, claims a queued run, and persists an attempt before executing each question. Results and aggregates are saved after each attempt. A second worker is rejected. Cancellation stops after the current attempted question returns; it does not kill an in-flight provider call.

On restart, the sole worker marks interrupted `running` runs `failed` and preserves their results. It does not silently remove failures or repeat partial model calls. Create a new run to retry. Queued runs remain queued. Infrastructure failures mark a run failed and cause a nonzero worker exit; ordinary question failures are retained and the run finishes `completed` with a nonzero failure count.

Corpus and embedding versions are checked before execution. Generation budgets are recorded and changes between queueing and execution fail the run explicitly. Model tags/digests and prompts are stored in the per-question query traces. Milestone 5 supports [controlled comparisons using materialized context](comparison.md); ordinary separately retrieved generation runs do not establish that control.

## Actual development export

`benchmarks/keyword-development-draft.json` was produced by the real worker against the original sample using PostgreSQL full-text, top-K=3, and draft development labels. It records all 24 attempts, source chunks, metrics, and actual timing. It is a saved development result, not a new inference response or a validated holdout result. The export includes dataset/corpus/configuration versions and questions; it contains no paid API outputs or invented figures.
