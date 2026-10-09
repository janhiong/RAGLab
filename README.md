# RAG Lab

A local experimentation platform for retrieval-augmented generation. Upload documents, inspect their chunks, and compare PostgreSQL full-text, vector cosine, and hybrid RRF retrieval.

**Implemented:** Next.js dashboard; FastAPI; PostgreSQL/pgvector; TXT, Markdown, and text-based PDF ingestion; source chunk inspection; local MiniLM embeddings; retrieval with source IDs, page references, scores, and timings; read-only mode; CI.

**Implemented in milestone 3:** opt-in Ollama generation, grounded answers with source references, abstention, and persisted query traces.

**Implemented in milestone 5:** experiment comparisons, failure drill-down, frozen-context local-model runs, and a measured provisional keyword-retrieval change. See [comparison workflow and case study](docs/comparison.md).

**Implemented in milestone 4:** versioned dataset import, a durable evaluation worker, retrieval/latency/failure metrics, manual answer-review forms, and a real provisional development export.

**Not implemented yet:** controlled model comparison, human-validated labels/holdout results, or deployed public hosting. Search returns source evidence; the playground generates answers only when a local model is available. No benchmark scores are fabricated.

See [the full project plan](docs/project-plan.md) for proposed later milestones.

## Requirements

Python 3.11+ (tested with 3.12), Node.js 22+, npm, and Docker Compose. No paid API or provider account is required. The development database credentials are local-only; replace them before any public deployment.

## Start locally

From the repository root:

```bash
docker compose up -d --wait db
python -m venv .venv
source .venv/bin/activate
pip install -e 'apps/api[dev]'
```

New database volumes run all migrations automatically. For an existing volume, apply the additional migrations:

```bash
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U raglab -d raglab < supabase/migrations/0002_ingestion.sql
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U raglab -d raglab < supabase/migrations/0003_query_traces.sql
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U raglab -d raglab < supabase/migrations/0004_evaluation.sql
```

Start the API in a terminal with the virtualenv activated:

```bash
cd apps/api
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal:

```bash
cd apps/web
npm ci
npm run dev
```

Open `http://localhost:3000` on your own machine; the default CORS origin is localhost. The API documentation is at `http://localhost:8000/docs`. Optional app settings are documented in each app's `.env.example` (copy to that app's `.env` only when needed). Never commit secrets.

## Try ingestion and keyword search

In the dashboard, upload `sample-corpus/retrieval-notes.md`. It is an original CC0 sample. Select the document and search for `cosine similarity`. Inspect chunk IDs, source text, and scores. Scanned and encrypted PDFs are unsupported; errors are shown instead of indexing empty text.

Uploads are limited to 5 MiB, 200 PDF pages, 200,000 extracted characters, and 500 chunks. TXT and Markdown use UTF-8. Chunking uses 180 whitespace-separated words with 30-word overlap, within each PDF page. This is word-based, not tokenizer-based: the embedding model can truncate chunks that exceed its token limit. The chunk configuration is versioned and preserved with the source. Duplicate file bytes return 409; document and chunk inserts are atomic.

The default upload indexes for keyword search. PostgreSQL `ts_rank_cd` is not BM25. Keyword search may miss paraphrases or return no results for stop words. Retrieval is limited to the selected document in this milestone; multi-document corpus selection is future work. Lists are paginated; the UI shows the latest 100 documents and first 100 inspected chunks.

## Enable vector and hybrid search

Run from the repository root with the API virtualenv activated:

```bash
pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cpu
pip install -e 'apps/api[vector]'
HF_HUB_DISABLE_XET=1 python scripts/download_embedding_model.py --output .models/all-MiniLM-L6-v2
```

The script downloads `sentence-transformers/all-MiniLM-L6-v2` at an immutable revision and writes provenance metadata. The 384-dimensional model is loaded locally on CPU; requests never download model files. TLS and normal download verification remain enabled. A new environment needs network access to Hugging Face and its weight CDN for the initial download. The cloud allowlist additions are `huggingface.co`, `cas-bridge.xethub.hf.co`, `cas-server.xethub.hf.co`, and `us.aws.cdn.hf.co`.

Restart the API from `apps/api`:

```bash
EMBEDDING_MODEL_PATH=../../.models/all-MiniLM-L6-v2 uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Reload documents in the dashboard, select a document, and click **Index vectors**. Then choose vector or hybrid retrieval. Existing keyword chunks are retained and augmented atomically. Missing model files return an explicit error. Vector requests require a matching embedding version; there is no fallback that silently substitutes lexical retrieval.

Vector retrieval uses exact cosine search, appropriate for a small portfolio corpus. Hybrid combines up to four times top-K candidates from each strategy using RRF with k=60 and deduplicates by chunk ID. Similarity, lexical rank, and RRF scores are different quantities, not correctness probabilities.

## Enable local RAG answers (milestone 3)

Ollama generation works with keyword retrieval, so it does not require the MiniLM download. Generation is disabled by default and requires an installed, explicitly configured model. On a CPU machine, start with `qwen2.5:1.5b`; allow roughly 2–4 GiB of model/runtime memory plus the other applications. Larger models need separate hardware checks.

From the repository root:

```bash
docker compose --profile generation up -d ollama
docker compose exec ollama ollama pull qwen2.5:1.5b
```

Restart the native API from `apps/api` with its virtualenv activated:

```bash
GENERATION_ENABLED=true uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In the dashboard, refresh the playground, select a document/model, and ask `What is cosine similarity?`. Use **PostgreSQL full-text** until a vector model is available. Click inline references such as `[S1]` to inspect the exact excerpt, filename, and page used in the prompt.

`GET /capabilities` reports live generation only when Ollama is reachable and a configured model is installed. `/health` reports configuration, not model readiness. Models can still fail during inference. The UI shows those failures and their trace IDs, rather than presenting a stored answer as a new response.

Configure `OLLAMA_MODELS` as a JSON array in the API environment to allow other model tags; arbitrary request-specified models are rejected. `OLLAMA_URL` defaults to the local service. The compose API service uses `http://ollama:11434`; to enable it, set `GENERATION_ENABLED=true` when starting the API with the generation profile. The optional API Docker image remains unvalidated in this cloud runner because of build-container DNS.

### Context, citations, and traces

The API uses prompt version `grounded-json-v1`, temperature 0, seed 42, a 384-token default output budget, and up to 10,000 characters of whole source chunks. Oversized chunks are excluded instead of silently cut in half; if no retrieved chunk fits, the request fails. Character budgeting is approximate: multilingual text or long questions can exceed the provider's tokenizer context window, so token-aware budgeting is future work.

Models return structured JSON. The backend rejects unknown IDs, missing references, inconsistent inline/reference lists, and malformed or truncated output. Citation IDs confirm membership in the supplied context; they do **not** establish correctness or faithfulness. Those require the later evaluation milestone. Source excerpts are marked as untrusted data in the prompt; prompt instructions alone do not guarantee resistance to document injection.

If retrieval finds no source, the API returns a deterministic no-evidence abstention and labels `generation_performed=false`; Ollama is not called. A model can also abstain when retrieved evidence is insufficient. Abstention text is canonical and includes no unsupported factual answer.

A single-process API permits one generation request at a time (429 when busy). Provider timeouts return 504. Connection/model availability failures return 503. Transient 429/503 responses are retried at most once; timed-out generation is not retried. The default provider timeout is 90 seconds and configurable up to 300 seconds. CPU generation may take a minute.

The database saves the question, retrieval/configuration versions, exact included excerpts, system prompt, model tag/digest, token counts when reported, timing, result, and errors. Malformed answer JSON and invalid citation output are retained in failed traces for diagnosis, but never displayed as an accepted answer. `GET /queries/{trace_id}` reads a saved trace. Query traces contain uploaded document text and questions; keep the API private. If the API process is interrupted, a trace may remain `running`; automated interruption recovery is future work. Deleting a document currently cascades to its traces.

### Cloud model provisioning

The model registry redirects weights to a separate CDN. Required additions are `registry.ollama.ai` and `dd20bb891979d25aebc8bec07b2b3bbc.r2.cloudflarestorage.com`, saved in the environment draft. The current cloud proxy still denies the CDN; review/save the network settings before retrying.

If a Docker container cannot use the host proxy, provision the model through the host with the API virtualenv:

```bash
python scripts/pull_ollama_model.py --model qwen2.5:1.5b --directory /workspace/raglab-ollama/models
OLLAMA_DATA_PATH=/workspace/raglab-ollama docker compose --profile generation up -d ollama
```

This helper uses the official public registry and verifies each blob's SHA-256 and byte count before publishing its manifest. TLS verification stays enabled; failed downloads are not accepted. Use the same `OLLAMA_DATA_PATH` on later compose commands so the model volume stays consistent. Model tags can change upstream; actual loaded manifest digests are recorded in each trace.

## Run evaluation (milestone 4)

See [evaluation methodology](docs/evaluation.md) for denominators, draft-label limitations, review rubrics, and restart behavior.

1. Upload `sample-corpus/retrieval-notes.md` using the dashboard. Copy its document ID from `GET /documents` or the API docs.
2. With the API virtualenv active, import the starter labels from the repository root:

   ```bash
   python scripts/import_dataset.py datasets/retrieval-notes-draft.json --document-id DOCUMENT_UUID
   ```

3. Refresh the Evaluation panel, select the dataset, and queue a **retrieval-only / keyword / development** run. Draft-label runs display a provisional warning; holdout requires manually reviewed labels.
4. Run the worker from `apps/api`:

   ```bash
   python -m app.evaluation.worker --drain
   ```

   This processes queued runs sequentially and exits when the queue is empty. To process one specific queued run, use `--run-id RUN_UUID`; without arguments it processes at most one queued run. The UI polls selected queued/running runs and shows persisted results.
5. Inspect per-question references, retrieved chunks, errors, and metrics. Cancel queued/running runs from the UI. Generation runs require the working Ollama setup; answer scores remain **Not measured** until reviewed with a rationale.
6. From the repository root, export a terminal run to a new file:

   ```bash
   python scripts/export_experiment.py RUN_UUID --output benchmarks/my-run.json
   ```

   Export refuses to overwrite an existing file. It preserves the dataset, configuration, per-question results, and observed metrics. Keep user-uploaded private content out of public commits.

The checked-in keyword development export is an actual measurement on **draft** labels. It is not a validated quality claim. The starter dataset needs your manual review before holdout evaluation.

## Validate

```bash
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/ready
cd apps/api
RAGLAB_INTEGRATION=1 pytest
```

To exercise actual model inference as well, use the model path relative to `apps/api`:

```bash
EMBEDDING_MODEL_PATH=../../.models/all-MiniLM-L6-v2 RAGLAB_INTEGRATION=1 RAGLAB_MODEL_INTEGRATION=1 pytest
```

Unit tests can run without PostgreSQL using `pytest`; database and real-model checks are explicitly skipped when not enabled. Tests using deterministic test vectors validate SQL behavior only, while the separate real-model test checks semantic retrieval with the actual pinned model. Neither is a benchmark-quality evaluation.

To exercise a real Ollama answer with the pulled model running:

```bash
RAGLAB_INTEGRATION=1 RAGLAB_OLLAMA_INTEGRATION=1 pytest
```

From `apps/web`:

```bash
npm run build
npm run typecheck
```

`/health` checks the API process; `/ready` checks PostgreSQL, pgvector, and schema availability. Unavailable database endpoints return 503 rather than fake data.

## API

- `POST /documents`: multipart `file`, optional `with_vectors=true`.
- `GET /documents`: paginated documents (`limit`, `offset`).
- `GET /documents/{id}/chunks`: paginated source chunks.
- `POST /documents/{id}/index`: add or refresh vectors.
- `POST /search`: JSON `question`, `document_id`, `strategy` (`keyword`, `vector`, `hybrid`), `top_k` (1–20).
- `POST /query`: search parameters plus an optional configured `model`; generates a grounded answer.
- `GET /queries/{trace_id}`: persisted result or failure trace.
- `POST /datasets`, `GET /datasets`: quote-anchored import and versioned dataset inventory.
- `POST /experiments`, `GET /experiments/{id}`, `/experiments/{id}/results`: durable run creation, progress, and paginated outcomes.
- `POST /experiments/{id}/cancel`, `/experiments/{id}/results/{question_id}/review`: cancellation and manual review.
- `GET /capabilities`, `/overview`, `/experiments`, `/health`, `/ready`.

## Database and deployment

`docker compose down` stops services and retains the data volume. RLS is enabled with no public table policies. The local API connects as database owner; public deployment requires scoped backend credentials and reviewed policies. Database credentials must stay out of the frontend.

This is a local/private application. Set `PRIVATE_UPLOADS_ENABLED=false` before exposing a read-only public API; it disables uploads and vector indexing. Authentication, public-query rate limits, and worker concurrency controls are not implemented, so do not expose writable endpoints anonymously. The API Dockerfile installs the basic keyword workflow; vector dependencies/model provisioning need separate deployment configuration. Docker build-container DNS was unavailable in this cloud runner, so the optional API Docker image has not been validated here. Use the tested native API workflow.

## Current validation

49 tests pass against PostgreSQL, covering ingestion, retrieval, citation validation, abstention, persisted failures, concurrency, provider retry/timeout behavior, and model artifact checksums. Frontend production build and TypeScript checks pass. Browser checks verify the actual unavailable/model-missing states; successful citation rendering and abstention presentation use explicit test fixtures, not a real model.

Two real-model tests are explicitly skipped: the MiniLM weight CDN and Ollama weight CDN are blocked by the cloud proxy. Ollama 0.12.6 starts and answers its version/model-list endpoints, but no real LLM answer has been generated here. Review and save the recorded network requirements, retry provisioning, then enable the real-model tests. Do not treat the mocked tests as evidence of model quality or a benchmark.

## Next milestone

Prepare the portfolio launch: review dataset labels, validate actual local models, evaluate the reviewed holdout, and document deployment. No public deployment or validated holdout results are claimed yet.
