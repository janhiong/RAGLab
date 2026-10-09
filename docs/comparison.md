# Experiment comparison and failure analysis

Milestone 5 adds a comparison dashboard, paired question inspection, observable failure tags, and controlled generation runs using frozen retrieval input. No new database migration is needed; configurations and saved results use the existing JSONB columns.

## Compare existing runs

In **Compare & diagnose**, select a baseline and candidate and click **Compare runs**. Both must be terminal and use exactly the same dataset ID/version, corpus version, split, and evaluation mode. Retrieval configuration may differ, and both configurations are shown. The API is `GET /comparisons?baseline=UUID&candidate=UUID`.

Metrics come from persisted attempts. Missing attempts are shown explicitly and suppress all deltas; attempted failures stay in the denominators. Unmeasured answer scores stay null. Manual score deltas are withheld when the reviewed question IDs differ. Inspect review coverage and rationales for scoring consistency. A complete run can contain failed attempts; completeness does not mean every request succeeded. Positive deltas improve Recall/MRR but increase latency and failure rate.

Failure filters include retrieval misses (Recall below 1 on answerable questions), request failures, missing attempts, answerable abstentions, answers to unanswerable questions, and manual review issues. These are symptoms, not automatically proven root causes. Reference labels, retrieved excerpts, generated answers, and errors appear together for inspection. All questions are returned, including those beyond the evaluation table's first 100 rows.

## Freeze context for two local models

Enable generation and configure/install two distinct models in `OLLAMA_MODELS`. Select a completed successful retrieval run as the baseline, then open **Queue two local models with identical saved context**. The API equivalent is:

```json
POST /model-comparisons
{"source_run_id":"RETRIEVAL_RUN_UUID","models":["qwen2.5:1.5b","YOUR_SECOND_MODEL"]}
```

The API atomically creates two queued experiments. Each stores the same materialized retrieval input and SHA256 of the budgeted contexts. Run the existing sequential worker:

```bash
cd apps/api
python -m app.evaluation.worker --drain
```

Refresh and compare the returned run IDs. Generation never searches again: it uses saved chunk ordering, excerpt text, citation aliases, question, prompt, schema, temperature 0, seed 42, context window 8192, four inference threads, and recorded output/context budgets. Prompt or budget drift fails the run. Actual system/user messages and schema are hashed per generated question; model digests, usage, traces, and raw failed output are retained. Successful generated pairs must have identical actual input hashes to receive the controlled-context label. A timeout is still an attempted failure, not a removed sample. Empty contexts use deterministic abstention and make no model call. The label establishes input control, not demonstrated answer quality or successful inference for every question.

Both models run on the same local worker, sequentially. Hardware and background load affect latency; this implementation does not normalize cross-machine timing. Retrieval stage timings in frozen runs are copied from the source measurement; total timings measure replay plus generation, and do not include repeating retrieval. Read-only mode disables creating comparisons but permits viewing saved results. There is no automatic model judge.

## Measured development change

The baseline keyword query uses PostgreSQL web-search semantics, which combine ordinary question words with AND. The optional `keyword_mode=any_term` builds an OR query from PostgreSQL's English lexemes, preserving parameter binding and ignoring punctuation/stop words. It broadens lexical recall and can retrieve irrelevant excerpts. The baseline default is unchanged. Choose **Any term (broader recall)** in Evaluation to queue a candidate.

The actual export is [keyword-any-term-comparison-draft.json](../benchmarks/keyword-any-term-comparison-draft.json). Both runs used the same corpus, dataset version, development split, keyword ranker, and top-K 3: 24 attempts, 19 answerable questions, 5 unanswerable questions, zero request failures. Labels are unreviewed; the corpus has only two coarse chunks.

| Metric | Baseline | Any-term candidate |
| --- | ---: | ---: |
| Recall@3 | 0.5789 | 1.0000 |
| MRR | 0.5789 | 0.9474 |
| Total p50 ms | 23.825 | 23.010 |
| Total p95 ms | 29.899 | 37.404 |

Three concrete failure cases:

| Question | Baseline evidence | Hypothesis | Candidate result |
| --- | --- | --- | --- |
| q09: Where can keyword search work well? | No chunks; source says “effective for exact technical terms” | AND requires question terms absent from the source | Relevant chunk retrieved, Recall 1 / RR 1 |
| q13: Why avoid mixing raw retrieval scores? | No chunks; source says scores do not “have the same scale” | Surface wording differs and AND removes the match | Relevant chunk retrieved, Recall 1 / RR 1 |
| q14: How should fused matches be deduplicated? | No chunks; source says “Deduplicate matches by chunk identifier” | The extra term “fused” removes otherwise useful lexical overlap | Relevant chunk retrieved, Recall 1 / RR 1 |

The change recovers eight baseline misses. Two candidate answers rank the relevant chunk second; broader matching has a precision/ranking cost. Higher p95 is one observation across runs at different times, not a statistically established regression. Unanswerable retrieval cannot establish answer abstention without generation. Correctness and faithfulness remain unmeasured. Human label review, real vector/model provisioning, a larger corpus, repeated measurements, and reviewed holdout evaluation remain outstanding; no held-out improvement is claimed.
