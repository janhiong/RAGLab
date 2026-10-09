# RAG Lab

A local experimentation platform for retrieval-augmented generation. Upload documents, inspect their chunks, and compare PostgreSQL full-text, vector cosine, and hybrid RRF retrieval.

**Implemented:** Next.js dashboard; FastAPI; PostgreSQL/pgvector; TXT, Markdown, and text-based PDF ingestion; source chunk inspection; local MiniLM embeddings; retrieval with source IDs, page references, scores, and timings; read-only mode; CI.

**Not implemented yet:** Ollama generation, benchmark datasets/worker, model comparison, or measured quality metrics. Returned chunks are evidence, not generated answers. No benchmark scores are fabricated.

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

New database volumes run both migrations automatically. For an existing volume, apply the additional migration:

```bash
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U raglab -d raglab < supabase/migrations/0002_ingestion.sql
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
- `GET /capabilities`, `/overview`, `/experiments`, `/health`, `/ready`.

## Database and deployment

`docker compose down` stops services and retains the data volume. RLS is enabled with no public table policies. The local API connects as database owner; public deployment requires scoped backend credentials and reviewed policies. Database credentials must stay out of the frontend.

This is a local/private application. Set `PRIVATE_UPLOADS_ENABLED=false` before exposing a read-only public API; it disables uploads and vector indexing. Authentication, public-query rate limits, and worker concurrency controls are not implemented, so do not expose writable endpoints anonymously. The API Dockerfile installs the basic keyword workflow; vector dependencies/model provisioning need separate deployment configuration. Docker build-container DNS was unavailable in this cloud runner, so the optional API Docker image has not been validated here. Use the tested native API workflow.

## Current validation

The ingestion/retrieval suite passes 21 tests against PostgreSQL, including vector SQL and RRF tests using deterministic test vectors. Frontend build/type checking and browser upload, source inspection, keyword search, duplicate/error handling, and mobile layout were verified. The separate real-MiniLM test is currently skipped: the cloud proxy allows model configuration downloads but denies the weight CDN. Actual model inference and semantic retrieval are not yet verified here. The required domains are saved in the environment draft; review/save those network changes before retrying the download.

## Next milestone

Add Ollama generation with validated citation IDs, then a persistent evaluation worker and manually labeled datasets. Model comparisons must use identical materialized context. No deployment or measured quality results are claimed yet.
