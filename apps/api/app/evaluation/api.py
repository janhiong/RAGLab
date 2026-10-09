import hashlib
import json
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from psycopg.types.json import Jsonb

from app.db import connect, settings
from app.evaluation.metrics import aggregate
from app.generation import PROMPT_VERSION

router = APIRouter()


def writable():
    if not settings.private_uploads_enabled:
        raise HTTPException(403, "Writes are disabled in read-only mode.")


class Question(BaseModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    question: str = Field(min_length=1, max_length=2000)
    reference_answer: str = Field(min_length=1, max_length=6000)
    relevant_quotes: list[str] = Field(default_factory=list, max_length=20)
    category: str = Field(default="factual", max_length=100)
    split: Literal["development", "holdout"] = "development"
    answerable: bool = True

    @model_validator(mode="after")
    def labels(self):
        if self.answerable != bool(self.relevant_quotes) or any(
            not quote.strip() or len(quote) > 2000 for quote in self.relevant_quotes
        ):
            raise ValueError(
                "Answerable questions require nonempty source quotes; unanswerable questions must have none."
            )
        return self


class DatasetImport(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    document_id: UUID
    reviewed: bool = False
    questions: list[Question] = Field(min_length=1, max_length=500)


@router.post("/datasets", status_code=201)
def import_dataset(request: DatasetImport):
    writable()
    if len({q.id for q in request.questions}) != len(request.questions):
        raise HTTPException(422, "Question IDs must be unique.")
    try:
        with connect() as c:
            doc = c.execute(
                "SELECT corpus_version FROM documents WHERE id=%s",
                (request.document_id,),
            ).fetchone()
            if not doc:
                raise HTTPException(404, "Document not found")
            chunks = c.execute(
                "SELECT id,content FROM chunks WHERE document_id=%s",
                (request.document_id,),
            ).fetchall()
            questions = []
            for question in request.questions:
                ids = set()
                for quote in question.relevant_quotes:
                    matches = [
                        str(chunk["id"])
                        for chunk in chunks
                        if " ".join(quote.split()) in chunk["content"]
                    ]
                    if not matches:
                        raise HTTPException(
                            422,
                            f"Source quote for {question.id} was not found in the indexed chunks.",
                        )
                    ids.update(matches)
                questions.append(
                    dict(question.model_dump(), relevant_chunk_ids=sorted(ids))
                )
            payload = {
                "questions": questions,
                "corpus_version": doc["corpus_version"],
                "reviewed": request.reviewed,
            }
            version = hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest()
            return c.execute(
                "INSERT INTO datasets(name,version,document_id,corpus_version,reviewed,questions) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id,name,version,reviewed",
                (
                    request.name,
                    version,
                    request.document_id,
                    doc["corpus_version"],
                    request.reviewed,
                    Jsonb(questions),
                ),
            ).fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "This dataset version already exists.") from None
    except psycopg.Error:
        raise HTTPException(503, "Dataset storage unavailable.") from None


@router.get("/datasets")
def datasets():
    with connect() as c:
        return {
            "items": c.execute(
                "SELECT id,name,version,document_id,corpus_version,reviewed,jsonb_array_length(questions) AS question_count FROM datasets ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        }


class RunRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    dataset_id: UUID
    strategy: Literal["keyword", "vector", "hybrid"] = "keyword"
    top_k: int = Field(default=5, ge=1, le=20)
    split: Literal["development", "holdout"] = "development"
    mode: Literal["retrieval", "generation"] = "retrieval"
    model: str | None = Field(default=None, max_length=100)


@router.post("/experiments", status_code=201)
def create_run(request: RunRequest):
    writable()
    with connect() as c:
        dataset = c.execute(
            "SELECT * FROM datasets WHERE id=%s", (request.dataset_id,)
        ).fetchone()
        if not dataset:
            raise HTTPException(404, "Dataset not found")
        if request.split == "holdout" and not dataset["reviewed"]:
            raise HTTPException(422, "Holdout runs require manually reviewed labels.")
        if not any(q["split"] == request.split for q in dataset["questions"]):
            raise HTTPException(422, "The selected split has no questions.")
        if request.mode == "generation" and (
            not settings.generation_enabled
            or request.model not in settings.ollama_models
        ):
            raise HTTPException(422, "Enable generation and select a configured model.")
        doc = c.execute(
            "SELECT embedding_version FROM documents WHERE id=%s",
            (dataset["document_id"],),
        ).fetchone()
        config = request.model_dump(mode="json")
        config["embedding_version"] = doc["embedding_version"]
        config["generation_settings"] = {
            "max_tokens": settings.generation_max_tokens,
            "context_chars": settings.generation_context_chars,
            "timeout_seconds": settings.generation_timeout_seconds,
        }
        config.update(
            document_id=str(dataset["document_id"]),
            dataset_reviewed=dataset["reviewed"],
            prompt_version=PROMPT_VERSION,
            seed=42,
            temperature=0,
        )
        return c.execute(
            "INSERT INTO experiments(name,status,configuration,corpus_version,dataset_version,dataset_id) VALUES (%s,'queued',%s,%s,%s,%s) RETURNING id,status",
            (
                request.name,
                Jsonb(config),
                dataset["corpus_version"],
                dataset["version"],
                dataset["id"],
            ),
        ).fetchone()


@router.get("/experiments/{run_id}")
def run_detail(run_id: UUID):
    with connect() as c:
        row = c.execute("SELECT * FROM experiments WHERE id=%s", (run_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Experiment not found")
        dataset = c.execute(
            "SELECT questions FROM datasets WHERE id=%s", (row["dataset_id"],)
        ).fetchone()
        row["total"] = (
            sum(
                q["split"] == row["configuration"].get("split")
                for q in dataset["questions"]
            )
            if dataset
            else 0
        )
        row["processed"] = c.execute(
            "SELECT count(*) AS count FROM experiment_results WHERE experiment_id=%s",
            (run_id,),
        ).fetchone()["count"]
        return row


@router.get("/experiments/{run_id}/results")
def run_results(
    run_id: UUID, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
):
    with connect() as c:
        if not c.execute(
            "SELECT id FROM experiments WHERE id=%s", (run_id,)
        ).fetchone():
            raise HTTPException(404, "Experiment not found")
        return {
            "items": c.execute(
                "SELECT * FROM experiment_results WHERE experiment_id=%s ORDER BY question_id LIMIT %s OFFSET %s",
                (run_id, limit, offset),
            ).fetchall()
        }


@router.post("/experiments/{run_id}/cancel")
def cancel(run_id: UUID):
    writable()
    with connect() as c:
        row = c.execute(
            "UPDATE experiments SET status='cancelled',completed_at=now() WHERE id=%s AND status IN ('queued','running') RETURNING id,status",
            (run_id,),
        ).fetchone()
        if not row:
            raise HTTPException(409, "Experiment is absent or already terminal.")
        return row


class Review(BaseModel):
    correctness: int = Field(ge=0, le=2)
    faithfulness: int = Field(ge=0, le=2)
    rationale: str = Field(min_length=1, max_length=3000)


@router.post("/experiments/{run_id}/results/{question_id}/review")
def review(run_id: UUID, question_id: str, request: Review):
    writable()
    with connect() as c:
        run = c.execute(
            "SELECT status FROM experiments WHERE id=%s FOR UPDATE", (run_id,)
        ).fetchone()
        if not run or run["status"] not in ("completed", "failed", "cancelled"):
            raise HTTPException(409, "Review a terminal run.")
        result = c.execute(
            "UPDATE experiment_results SET review=%s WHERE experiment_id=%s AND question_id=%s AND status='completed' AND answer IS NOT NULL RETURNING question_id",
            (Jsonb(request.model_dump()), run_id, question_id),
        ).fetchone()
        if not result:
            raise HTTPException(
                422, "Only completed generated answers can receive answer reviews."
            )
        rows = c.execute(
            "SELECT * FROM experiment_results WHERE experiment_id=%s", (run_id,)
        ).fetchall()
        c.execute(
            "UPDATE experiments SET aggregate_metrics=%s WHERE id=%s",
            (Jsonb(aggregate(rows)), run_id),
        )
        return result
