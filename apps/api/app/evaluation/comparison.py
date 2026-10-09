"""Comparable terminal runs and controlled generation from saved retrieval inputs."""

import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from app.db import connect, settings
from app.evaluation.api import writable
from app.evaluation.metrics import aggregate
from app.generation import prepare_context, PROMPT_VERSION, SYSTEM_PROMPT

router = APIRouter()
TERMINAL = {"completed", "failed", "cancelled"}


class ModelComparison(BaseModel):
    source_run_id: UUID
    models: list[str] = Field(min_length=2, max_length=2)


@router.post("/model-comparisons", status_code=201)
def create_model_comparison(request: ModelComparison):
    writable()
    if (
        len(set(request.models)) != 2
        or not settings.generation_enabled
        or any(m not in settings.ollama_models for m in request.models)
    ):
        raise HTTPException(
            422, "Enable generation and select two distinct configured models."
        )
    with connect() as c:
        source = c.execute(
            "SELECT * FROM experiments WHERE id=%s", (request.source_run_id,)
        ).fetchone()
        if not source:
            raise HTTPException(404, "Source experiment not found")
        rows = c.execute(
            "SELECT * FROM experiment_results WHERE experiment_id=%s ORDER BY question_id",
            (request.source_run_id,),
        ).fetchall()
        dataset = c.execute(
            "SELECT * FROM datasets WHERE id=%s", (source["dataset_id"],)
        ).fetchone()
        config = source["configuration"]
        if not dataset or not config.get("split"):
            raise HTTPException(422, "Use a dataset-backed retrieval run.")
        expected = {
            q["id"] for q in dataset["questions"] if q["split"] == config["split"]
        }
        if (
            source["status"] != "completed"
            or config["mode"] != "retrieval"
            or {r["question_id"] for r in rows} != expected
            or any(r["status"] != "completed" or r["retrieval"] is None for r in rows)
        ):
            raise HTTPException(
                422,
                "Use a complete successful retrieval run covering the selected split.",
            )
        inputs = {r["question_id"]: r["retrieval"] for r in rows}
        # Freeze the budget as well as the source ordering. Worker rejects budget drift.
        contexts = {
            key: prepare_context(value["items"], settings.generation_context_chars)
            for key, value in inputs.items()
        }
        fingerprint = hashlib.sha256(
            json.dumps(contexts, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        created = []
        # One transaction: both runs exist or neither does. Configuration matches normal worker runs.
        for model in request.models:
            run_config = dict(
                config,
                mode="generation",
                model=model,
                prompt_version=PROMPT_VERSION,
                system_prompt=SYSTEM_PROMPT,
                frozen_inputs=inputs,
                context_sha256=fingerprint,
                source_run_id=str(request.source_run_id),
                generation_settings={
                    "max_tokens": settings.generation_max_tokens,
                    "context_chars": settings.generation_context_chars,
                    "timeout_seconds": settings.generation_timeout_seconds,
                },
            )
            created.append(
                c.execute(
                    "INSERT INTO experiments(name,status,configuration,corpus_version,dataset_version,dataset_id) VALUES (%s,'queued',%s,%s,%s,%s) RETURNING id,status",
                    (
                        f"Frozen context · {model}",
                        Jsonb(run_config),
                        source["corpus_version"],
                        source["dataset_version"],
                        source["dataset_id"],
                    ),
                ).fetchone()
            )
        return {"runs": created, "context_sha256": fingerprint}


def failure_tags(row):
    if row is None:
        return ["not_attempted"]
    tags = []
    if row["status"] == "failed":
        tags.append("request_failure")
    if row["question"]["answerable"] and (row["metrics"].get("recall_at_k") or 0) < 1:
        tags.append("retrieval_miss")
    answer = row.get("answer")
    if answer and answer.get("abstained") and row["question"]["answerable"]:
        tags.append("answerable_abstention")
    if answer and not answer.get("abstained") and not row["question"]["answerable"]:
        tags.append("unsupported_answer")
    if row.get("review") and (
        row["review"]["correctness"] < 2 or row["review"]["faithfulness"] < 2
    ):
        tags.append("manual_review_issue")
    return tags


@router.get("/comparisons")
def compare(baseline: UUID, candidate: UUID):
    if baseline == candidate:
        raise HTTPException(422, "Select two different experiments.")
    with connect() as c:
        runs = [
            c.execute("SELECT * FROM experiments WHERE id=%s", (key,)).fetchone()
            for key in (baseline, candidate)
        ]
        if not all(runs):
            raise HTTPException(404, "Experiment not found")
        a, b = runs
        if any(r["status"] not in TERMINAL for r in runs):
            raise HTTPException(409, "Comparison requires terminal runs.")
        if any(
            a[key] != b[key]
            for key in ("dataset_id", "dataset_version", "corpus_version")
        ) or any(
            a["configuration"].get(key) != b["configuration"].get(key)
            for key in ("split", "mode")
        ):
            raise HTTPException(
                422,
                "Compare the same dataset version, corpus, split, and evaluation mode.",
            )
        dataset = c.execute(
            "SELECT questions,reviewed FROM datasets WHERE id=%s", (a["dataset_id"],)
        ).fetchone()
        if not dataset:
            raise HTTPException(422, "Use dataset-backed experiments.")
        questions = [
            q for q in dataset["questions"] if q["split"] == a["configuration"]["split"]
        ]
        results = [
            {
                r["question_id"]: r
                for r in c.execute(
                    "SELECT * FROM experiment_results WHERE experiment_id=%s",
                    (run["id"],),
                ).fetchall()
            }
            for run in runs
        ]
    metrics = [aggregate(list(rows.values())) for rows in results]
    complete = all(set(rows) == {q["id"] for q in questions} for rows in results)
    controlled = (
        complete
        and a["configuration"].get("context_sha256") is not None
        and all(
            a["configuration"].get(key) == b["configuration"].get(key)
            for key in (
                "source_run_id",
                "context_sha256",
                "generation_settings",
                "prompt_version",
                "system_prompt",
                "seed",
                "temperature",
            )
        )
    )
    # Successful generated pairs must also have exactly matching actual provider inputs.
    if controlled:
        for question in questions:
            answers = [rows[question["id"]].get("answer") for rows in results]
            if all(answer and answer.get("generation_performed") for answer in answers):
                controlled = (
                    controlled
                    and bool(answers[0].get("input_sha256"))
                    and answers[0]["input_sha256"] == answers[1].get("input_sha256")
                )
    deltas = {
        key: (
            metrics[1][key] - value
            if complete
            and isinstance(value, (int, float))
            and isinstance(metrics[1].get(key), (int, float))
            else None
        )
        for key, value in metrics[0].items()
    }
    reviewed_ids = [
        {key for key, row in rows.items() if row.get("review")} for rows in results
    ]
    if reviewed_ids[0] != reviewed_ids[1]:
        deltas["correctness"] = deltas["faithfulness"] = None
    for run in runs:
        run["configuration"] = {
            key: value
            for key, value in run["configuration"].items()
            if key != "frozen_inputs"
        }
    return {
        "baseline": a,
        "candidate": b,
        "metrics": metrics,
        "deltas": deltas,
        "complete_coverage": complete,
        "controlled_context": controlled,
        "reviewed_labels": dataset["reviewed"],
        "total": len(questions),
        "questions": [
            {
                "question": q,
                "baseline": results[0].get(q["id"]),
                "candidate": results[1].get(q["id"]),
                "baseline_failures": failure_tags(results[0].get(q["id"])),
                "candidate_failures": failure_tags(results[1].get(q["id"])),
            }
            for q in questions
        ],
    }
