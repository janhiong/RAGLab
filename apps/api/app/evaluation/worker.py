"""Sequential durable worker. One worker per database; interrupted runs fail explicitly."""

import argparse
import json
from time import perf_counter
from uuid import UUID

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from app.db import connect, settings
from app.documents import SearchRequest, search
from app.evaluation.metrics import aggregate, retrieval_metrics
from app.generation import QueryRequest, query

WORKER_LOCK = 724104


def save_result(run_id, question, status, retrieval, answer, error, elapsed_ms):
    metrics = retrieval_metrics(
        [str(item["id"]) for item in (retrieval or {}).get("items", [])],
        question["relevant_chunk_ids"],
    )
    metrics["abstention_correct"] = (
        (bool(answer["abstained"]) if answer else False)
        if not question["answerable"]
        and question.get("evaluation_mode") == "generation"
        else None
    )
    metrics["retrieval_ms"] = (retrieval or {}).get("retrieval_ms")
    metrics["generation_ms"] = (answer or {}).get("generation_ms")

    with connect() as c:
        c.execute(
            "INSERT INTO experiment_results(experiment_id,question_id,status,question,retrieval,answer,metrics,elapsed_ms,error) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(experiment_id,question_id) DO UPDATE SET status=EXCLUDED.status,retrieval=EXCLUDED.retrieval,answer=EXCLUDED.answer,metrics=EXCLUDED.metrics,elapsed_ms=EXCLUDED.elapsed_ms,error=EXCLUDED.error",
            (
                run_id,
                question["id"],
                status,
                Jsonb(question),
                (
                    Jsonb(json.loads(json.dumps(retrieval, default=str)))
                    if retrieval
                    else None
                ),
                Jsonb(answer) if answer else None,
                Jsonb(metrics),
                elapsed_ms,
                Jsonb(error) if error else None,
            ),
        )


def finish(run_id, status="completed", error=None):
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM experiment_results WHERE experiment_id=%s", (run_id,)
        ).fetchall()
        c.execute(
            "UPDATE experiments SET status=%s,error=%s,aggregate_metrics=%s,completed_at=now() WHERE id=%s AND status='running'",
            (status, error, Jsonb(aggregate(rows)), run_id),
        )


def recover_interrupted():
    with connect() as c:
        ids = [
            row["id"]
            for row in c.execute(
                "SELECT id FROM experiments WHERE status='running'"
            ).fetchall()
        ]
    for run_id in ids:
        finish(
            run_id,
            "failed",
            "Worker interrupted. Persisted attempts are retained; create a new run to retry.",
        )


def process(run):
    config = run["configuration"]
    if config["mode"] == "generation" and config.get("generation_settings") != {
        "max_tokens": settings.generation_max_tokens,
        "context_chars": settings.generation_context_chars,
        "timeout_seconds": settings.generation_timeout_seconds,
    }:
        finish(run["id"], "failed", "Generation configuration changed after queueing.")
        return
    with connect() as c:
        dataset = c.execute(
            "SELECT * FROM datasets WHERE id=%s", (run["dataset_id"],)
        ).fetchone()
        doc = c.execute(
            "SELECT corpus_version,embedding_version FROM documents WHERE id=%s",
            (dataset["document_id"],),
        ).fetchone()
    if doc["corpus_version"] != run["corpus_version"] or (
        config["strategy"] != "keyword"
        and doc["embedding_version"] != config.get("embedding_version")
    ):
        finish(
            run["id"],
            "failed",
            "Corpus or embedding version changed after the run was queued.",
        )
        return
    for question in dataset["questions"]:
        if question["split"] != config["split"]:
            continue
        question = dict(question, evaluation_mode=config["mode"])
        with connect() as c:
            if (
                c.execute(
                    "SELECT status FROM experiments WHERE id=%s", (run["id"],)
                ).fetchone()["status"]
                != "running"
            ):
                return
        started = perf_counter()
        # A crash between this durable attempt record and the final update remains an explicit failure.
        save_result(
            run["id"],
            question,
            "failed",
            None,
            None,
            {"code": "interrupted", "message": "Question attempt did not finish."},
            0,
        )
        retrieval = answer = error = None
        try:
            arguments = {
                "question": question["question"],
                "document_id": dataset["document_id"],
                "strategy": config["strategy"],
                "top_k": config["top_k"],
            }
            if config["mode"] == "retrieval":
                retrieval = search(SearchRequest(**arguments))
            else:
                answer = query(QueryRequest(**arguments, model=config["model"]))
                with connect() as c:
                    retrieval = c.execute(
                        "SELECT retrieval FROM query_traces WHERE id=%s",
                        (answer["trace_id"],),
                    ).fetchone()["retrieval"]
        except HTTPException as exc:
            error = {
                "code": "request_failed",
                "status_code": exc.status_code,
                "detail": exc.detail,
            }
            trace_id = (
                exc.detail.get("trace_id") if isinstance(exc.detail, dict) else None
            )
            if trace_id:
                with connect() as c:
                    trace = c.execute(
                        "SELECT retrieval,result FROM query_traces WHERE id=%s",
                        (trace_id,),
                    ).fetchone()
                    if trace:
                        retrieval = trace["retrieval"]
                        error["provider_output"] = (trace["result"] or {}).get(
                            "provider_output"
                        )
        except Exception as exc:
            # Keep diagnostics bounded; connection secrets are never included in exception text.
            error = {"code": "worker_error", "exception_type": type(exc).__name__}
        save_result(
            run["id"],
            question,
            "failed" if error else "completed",
            retrieval,
            answer,
            error,
            round((perf_counter() - started) * 1000, 2),
        )
        with connect() as c:
            rows = c.execute(
                "SELECT * FROM experiment_results WHERE experiment_id=%s", (run["id"],)
            ).fetchall()
            c.execute(
                "UPDATE experiments SET aggregate_metrics=%s WHERE id=%s",
                (Jsonb(aggregate(rows)), run["id"]),
            )
    finish(run["id"])


def work(run_id=None, drain=False):
    with connect() as lock_connection:
        if not lock_connection.execute(
            "SELECT pg_try_advisory_lock(%s) AS acquired", (WORKER_LOCK,)
        ).fetchone()["acquired"]:
            raise RuntimeError("Another evaluation worker is running.")
        recover_interrupted()
        while True:
            with connect() as c:
                row = c.execute(
                    "SELECT * FROM experiments WHERE status='queued' AND dataset_id IS NOT NULL"
                    + (" AND id=%s" if run_id else "")
                    + " ORDER BY created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED",
                    (run_id,) if run_id else (),
                ).fetchone()
                if row:
                    c.execute(
                        "UPDATE experiments SET status='running' WHERE id=%s",
                        (row["id"],),
                    )
            if not row:
                return
            try:
                process(row)
            except Exception:
                finish(
                    row["id"],
                    "failed",
                    "Worker infrastructure failure. Inspect service readiness and retained results.",
                )
                raise
            if run_id or not drain:
                return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=UUID)
    parser.add_argument(
        "--drain",
        action="store_true",
        help="Process queued runs sequentially, then exit",
    )
    args = parser.parse_args()
    work(args.run_id, args.drain)
