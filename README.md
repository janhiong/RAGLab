# RAG Lab

An experimentation platform for retrieval-augmented generation. This first milestone provides a Next.js dashboard, a FastAPI API, and PostgreSQL with pgvector. The dashboard reads real database counts and experiment history; it does not display invented benchmarks.

**Implemented:** application shell, health/readiness endpoints, overview and experiment reads, database schema, local Docker setup, and CI.

**Not implemented yet:** document ingestion, embeddings, retrieval, Ollama generation, benchmark worker, and comparison metrics. Live generation is explicitly unavailable.

See [the project plan](docs/project-plan.md) for the proposed full scope.

## Requirements

- Python 3.11+ (tested with 3.12)
- Node.js 22+ and npm
- Docker with Compose

No paid API or provider account is needed for this milestone. The database credentials below are for local development only. Do not use them in a public deployment.

## Run locally

From the repository root:

```bash
docker compose up -d db
python -m venv .venv
source .venv/bin/activate
pip install -e 'apps/api[dev]'
```

Start the API in a terminal:

```bash
cd apps/api
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
cd apps/web
npm ci
npm run dev
```

Open `http://localhost:3000` on your machine (the default CORS origin). The API documentation is at port 8000 under `/docs`. The frontend defaults to the local API. Optional settings are shown in each app's `.env.example`; copy to `.env` in that app directory only when customization is needed. Never commit secrets.

Alternatively, run the database and API together with `docker compose up -d --build`, then start the frontend separately.

## Verify

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
curl --fail http://127.0.0.1:8000/overview
cd apps/api
RAGLAB_INTEGRATION=1 pytest
```

`/health` checks the API process. `/ready` checks the database, pgvector, and required tables. Without a working database the database endpoints return 503 rather than fake data. Unit tests can run with `pytest` without a database; the database integration test is then skipped explicitly.

Frontend checks, from `apps/web`:

```bash
npm run build
npm run typecheck
```

## Database lifecycle

Compose initializes a new database volume using `supabase/migrations/0001_initial.sql`. Existing volumes are not automatically migrated. Apply the initial migration manually if necessary:

```bash
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U raglab -d raglab < supabase/migrations/0001_initial.sql
```

Stop services with `docker compose down`; the database volume is retained. RLS is enabled with no public access policies. The local API connects as the development database owner. Production should use scoped backend credentials and reviewed policies, not expose database credentials to the frontend.

## Next milestone

Implement parsing and chunking for TXT, Markdown, and text-based PDFs; index a small original corpus; then add vector retrieval and citation traces. Model selection and full benchmarking remain separate work. No deployment or benchmark results are claimed by this milestone.

## Cloud validation notes

The native API and PostgreSQL integration tests, frontend production build, TypeScript check, and browser empty/error/retry states were verified during development. The frontend dependency audit reported zero vulnerabilities.

The optional API Docker image build could not finish in the cloud runner because build containers could not resolve the package registry. Use the verified native API setup above in this runner. The Dockerfile is included for environments with working build-network access; its image has not been validated here.
