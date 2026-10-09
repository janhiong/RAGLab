import json
import os
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.db import settings
from app.evaluation.metrics import aggregate, percentile, retrieval_metrics
from app.evaluation.worker import WORKER_LOCK, work
from app.main import app

client = TestClient(app)


def test_retrieval_denominators_and_unanswerable():
    assert retrieval_metrics(["b", "b", "a"], ["a", "c"]) == {
        "recall_at_k": 0.5,
        "reciprocal_rank": 0.5,
    }
    assert retrieval_metrics([], []) == {"recall_at_k": None, "reciprocal_rank": None}
    rows = [
        {
            "status": "completed",
            "question": {"relevant_chunk_ids": ["a"]},
            "metrics": {"recall_at_k": 1, "reciprocal_rank": 1},
            "elapsed_ms": 10,
        },
        {
            "status": "failed",
            "question": {"relevant_chunk_ids": ["b"]},
            "metrics": {},
            "elapsed_ms": 30,
        },
        {
            "status": "completed",
            "question": {"relevant_chunk_ids": []},
            "metrics": {},
            "elapsed_ms": 20,
        },
    ]
    result = aggregate(rows)
    assert result["recall_at_k"] == 0.5 and result["mrr"] == 0.5
    assert result["failure_rate"] == pytest.approx(1 / 3)
    assert result["abstention_accuracy"] is None and result["correctness"] is None
    assert percentile([10, 20, 30], 0.95) == 29


@pytest.fixture
def dataset():
    if os.environ.get("RAGLAB_INTEGRATION") != "1":
        pytest.skip("Requires migrated PostgreSQL")
    doc = client.post(
        "/documents",
        files={
            "file": (
                "evaluation.txt",
                f"Cosine similarity measures angles between vectors. {uuid4()}".encode(),
            )
        },
    ).json()
    payload = {
        "name": "Test dataset",
        "document_id": doc["id"],
        "questions": [
            {
                "id": "a",
                "question": "cosine similarity",
                "reference_answer": "Angles between vectors",
                "relevant_quotes": ["Cosine similarity"],
                "answerable": True,
            },
            {
                "id": "b",
                "question": "absentlexeme",
                "reference_answer": "Unknown",
                "relevant_quotes": [],
                "answerable": False,
            },
            {
                "id": "h",
                "question": "vectors",
                "reference_answer": "Vectors",
                "relevant_quotes": ["vectors"],
                "split": "holdout",
                "answerable": True,
            },
        ],
    }
    response = client.post("/datasets", json=payload)
    assert response.status_code == 201, response.text
    item = response.json()
    yield item, doc, payload
    with psycopg.connect(settings.database_url) as c:
        c.execute(
            "DELETE FROM experiments WHERE dataset_id IN (SELECT id FROM datasets WHERE document_id=%s)",
            (doc["id"],),
        )
        c.execute("DELETE FROM datasets WHERE document_id=%s", (doc["id"],))
        c.execute("DELETE FROM documents WHERE id=%s", (doc["id"],))


def queue(dataset, **options):
    response = client.post(
        "/experiments",
        json={"name": "Test run", "dataset_id": dataset[0]["id"], **options},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_dataset_labels_and_holdout_guard(dataset):
    assert client.post("/datasets", json=dataset[2]).status_code == 409
    invalid = dict(
        dataset[2],
        questions=[
            dict(dataset[2]["questions"][0], relevant_quotes=["missing source"])
        ],
    )
    assert client.post("/datasets", json=invalid).status_code == 422
    assert (
        client.post(
            "/experiments",
            json={
                "name": "holdout",
                "dataset_id": dataset[0]["id"],
                "split": "holdout",
            },
        ).status_code
        == 422
    )


def test_worker_persists_actual_retrieval(dataset):
    run_id = queue(dataset)
    work(run_id)
    detail = client.get("/experiments/" + run_id).json()
    assert (
        detail["status"] == "completed" and detail["processed"] == detail["total"] == 2
    )
    metrics = detail["aggregate_metrics"]
    assert (
        metrics["recall_at_k"] == 1
        and metrics["mrr"] == 1
        and metrics["attempted"] == 2
    )
    assert metrics["abstention_accuracy"] is None and metrics["correctness"] is None
    assert (
        len(client.get(f"/experiments/{run_id}/results?limit=1").json()["items"]) == 1
    )
    assert (
        client.post(
            f"/experiments/{run_id}/results/a/review",
            json={"correctness": 2, "faithfulness": 2, "rationale": "test"},
        ).status_code
        == 422
    )


def test_failed_requests_remain_in_metrics(dataset, monkeypatch):
    def fail(*args):
        raise HTTPException(503, "Unavailable")

    monkeypatch.setattr("app.evaluation.worker.search", fail)
    run_id = queue(dataset)
    work(run_id)
    metrics = client.get("/experiments/" + run_id).json()["aggregate_metrics"]
    assert (
        metrics["failure_rate"] == 1
        and metrics["attempted"] == 2
        and metrics["recall_at_k"] == 0
    )
    assert metrics["abstention_accuracy"] is None


def test_worker_lock_and_interruption(dataset):
    run_id = queue(dataset)
    with psycopg.connect(settings.database_url) as lock:
        lock.execute("SELECT pg_advisory_lock(%s)", (WORKER_LOCK,))
        with pytest.raises(RuntimeError, match="Another"):
            work(run_id)
    with psycopg.connect(settings.database_url) as c:
        c.execute("UPDATE experiments SET status='running' WHERE id=%s", (run_id,))
    work()
    detail = client.get("/experiments/" + run_id).json()
    assert detail["status"] == "failed" and "interrupted" in detail["error"]


def test_cancellation_stays_terminal(dataset, monkeypatch):
    run_id = queue(dataset)
    from app.documents import search

    def cancel_during_question(request):
        assert client.post(f"/experiments/{run_id}/cancel").status_code == 200
        return search(request)

    monkeypatch.setattr("app.evaluation.worker.search", cancel_during_question)
    work(run_id)
    detail = client.get("/experiments/" + run_id).json()
    assert detail["status"] == "cancelled" and detail["processed"] == 1


def test_generated_answer_review_coverage(dataset, monkeypatch):
    monkeypatch.setattr(settings, "generation_enabled", True)
    monkeypatch.setattr(
        "app.generation.installed_models",
        lambda url: {settings.ollama_models[0]: "test-digest"},
    )
    monkeypatch.setattr(
        "app.generation.generate",
        lambda *args: {
            "content": json.dumps(
                {"answer": "Angles [S1]", "citations": ["S1"], "abstained": False}
            ),
            "attempts": 1,
            "token_usage": {"eval_count": 5},
        },
    )
    run_id = queue(dataset, mode="generation", model=settings.ollama_models[0])
    work(run_id)
    response = client.post(
        f"/experiments/{run_id}/results/a/review",
        json={
            "correctness": 2,
            "faithfulness": 1,
            "rationale": "Partial support reviewed against source",
        },
    )
    assert response.status_code == 200, response.text
    metrics = client.get("/experiments/" + run_id).json()["aggregate_metrics"]
    assert (
        metrics["manually_reviewed_count"] == 1
        and metrics["correctness"] == 2
        and metrics["faithfulness"] == 1
    )
    assert metrics["abstention_accuracy"] == 1


def test_changed_corpus_blocks_a_queued_run(dataset):
    run_id = queue(dataset)
    with psycopg.connect(settings.database_url) as c:
        c.execute(
            "UPDATE documents SET corpus_version=%s WHERE id=%s",
            ("changed-version", dataset[1]["id"]),
        )
    work(run_id)
    detail = client.get("/experiments/" + run_id).json()
    assert detail["status"] == "failed" and detail["processed"] == 0
    assert "version changed" in detail["error"]


def test_evaluation_writes_disabled_in_read_only_mode(dataset, monkeypatch):
    run_id = queue(dataset)
    monkeypatch.setattr(settings, "private_uploads_enabled", False)
    assert client.post("/datasets", json=dataset[2]).status_code == 403
    assert (
        client.post(
            "/experiments", json={"name": "blocked", "dataset_id": dataset[0]["id"]}
        ).status_code
        == 403
    )
    assert client.post(f"/experiments/{run_id}/cancel").status_code == 403
