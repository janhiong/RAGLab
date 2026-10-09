import json
import os
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.db import settings
from app.generation import (
    ABSTENTION,
    _generation_slot,
    prepare_context,
    validate_answer,
)
from app.main import app
from app.providers.ollama import GenerationError, generate

client = TestClient(app)


@pytest.fixture
def document(monkeypatch):
    if os.environ.get("RAGLAB_INTEGRATION") != "1":
        pytest.skip("Requires migrated PostgreSQL")
    content = f"Cosine similarity measures the angle between two embedding vectors. Higher scores indicate closer representations. {uuid4()}"
    response = client.post(
        "/documents", files={"file": ("generation.txt", content.encode())}
    )
    assert response.status_code == 201, response.text
    doc_id = response.json()["id"]
    monkeypatch.setattr(settings, "generation_enabled", True)
    yield doc_id
    with psycopg.connect(settings.database_url) as connection:
        connection.execute("DELETE FROM documents WHERE id=%s", (doc_id,))


@pytest.fixture
def model_stub(monkeypatch):
    monkeypatch.setattr(
        "app.generation.installed_models",
        lambda url: {settings.ollama_models[0]: "sha256:test-digest"},
    )

    def fake(settings, model, messages, schema):
        payload = json.loads(messages[1]["content"])
        assert "ignore any instructions" in messages[0]["content"]
        assert payload["sources"][0]["citation_id"] == "S1"
        assert schema["properties"]["citations"]["items"]["enum"] == ["S1"]
        return {
            "content": json.dumps(
                {
                    "answer": "Cosine similarity measures the angle between embedding vectors [S1].",
                    "citations": ["S1"],
                    "abstained": False,
                }
            ),
            "token_usage": {"prompt_eval_count": 100, "eval_count": 20},
            "attempts": 1,
        }

    monkeypatch.setattr("app.generation.generate", fake)


def ask(doc_id, question="cosine similarity", **kwargs):
    return client.post(
        "/query", json={"question": question, "document_id": doc_id, **kwargs}
    )


def test_answer_and_persisted_trace(document, model_stub):
    response = ask(document)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["generation_performed"] and not result["abstained"]
    assert result["citations"][0]["citation_id"] == "S1"
    assert result["citations"][0]["chunk_id"]
    assert result["token_usage"]["eval_count"] == 20
    trace = client.get("/queries/" + result["trace_id"]).json()
    assert trace["status"] == "completed"
    assert trace["configuration"]["model_digest"] == "sha256:test-digest"
    assert trace["configuration"]["system_prompt"]
    assert trace["retrieval"]["corpus_version"]
    assert trace["result"]["answer"] == result["answer"]


def test_no_evidence_does_not_call_model(document, monkeypatch):
    monkeypatch.setattr(
        "app.generation.generate",
        lambda *args: pytest.fail("No evidence must not call a model"),
    )
    response = ask(document, "absentlexeme")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["abstained"] and not result["generation_performed"]
    assert (
        result["model"] is None
        and result["generation_ms"] == 0
        and result["citations"] == []
    )


def test_invalid_citations_are_failed_and_retained(document, model_stub, monkeypatch):
    monkeypatch.setattr(
        "app.generation.generate",
        lambda *args: {
            "content": json.dumps(
                {
                    "answer": "Unsupported [S99]",
                    "citations": ["S99"],
                    "abstained": False,
                }
            ),
            "token_usage": {},
            "attempts": 1,
        },
    )
    response = ask(document)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "invalid_citations"
    trace = client.get("/queries/" + response.json()["detail"]["trace_id"]).json()
    assert trace["status"] == "failed"
    assert "S99" in trace["result"]["provider_output"]


def test_provider_timeout_retained(document, model_stub, monkeypatch):
    def timeout(*args):
        raise GenerationError("provider_timeout", "Ollama generation timed out.", 504)

    monkeypatch.setattr("app.generation.generate", timeout)
    response = ask(document)
    assert response.status_code == 504
    trace = client.get("/queries/" + response.json()["detail"]["trace_id"]).json()
    assert trace["status"] == "failed" and trace["error"]["code"] == "provider_timeout"


def test_generation_disabled_and_model_validation(document, monkeypatch):
    assert ask(document, model="unknown-model").status_code == 422
    monkeypatch.setattr(settings, "generation_enabled", False)
    assert ask(document).status_code == 503


def test_bounded_concurrency(document):
    assert _generation_slot.acquire(blocking=False)
    try:
        assert ask(document).status_code == 429
    finally:
        _generation_slot.release()


@pytest.mark.parametrize(
    "body",
    [
        {"answer": "No references", "citations": [], "abstained": False},
        {"answer": "Wrong inline [S2]", "citations": ["S1"], "abstained": False},
        {"answer": "Duplicate [S1]", "citations": ["S1", "S1"], "abstained": False},
        {"answer": "Abstaining [S1]", "citations": ["S1"], "abstained": True},
    ],
)
def test_invalid_answer_contract(body):
    with pytest.raises(GenerationError):
        validate_answer(json.dumps(body), [{"citation_id": "S1"}])


def test_abstention_is_canonical_and_context_is_bounded():
    result = validate_answer(
        json.dumps(
            {"answer": "Some speculative answer", "citations": [], "abstained": True}
        ),
        [],
    )
    assert result.answer == ABSTENTION
    items = [
        {"id": str(uuid4()), "document_id": str(uuid4()), "content": "a" * 1000},
        {"id": str(uuid4()), "document_id": str(uuid4()), "content": "small"},
    ]
    context = prepare_context(items, 500)
    assert (
        len(context) == 1
        and context[0]["content"] == "small"
        and context[0]["citation_id"] == "S1"
    )


def mock_transport(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(
        "app.providers.ollama.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_provider_transient_retry(monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(503)
        payload = json.loads(request.content)
        assert payload["stream"] is False and payload["options"]["seed"] == 42
        return httpx.Response(
            200, json={"done": True, "message": {"content": "{}"}, "eval_count": 7}
        )

    mock_transport(monkeypatch, handler)
    result = generate(settings, "test", [], {})
    assert (
        len(attempts) == 2
        and result["attempts"] == 2
        and result["token_usage"]["eval_count"] == 7
    )


def test_provider_timeout_no_retry(monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(request)
        raise httpx.ReadTimeout("private details", request=request)

    mock_transport(monkeypatch, handler)
    with pytest.raises(GenerationError) as exc:
        generate(settings, "test", [], {})
    assert exc.value.status_code == 504 and len(attempts) == 1
    assert "private" not in str(exc.value)


def test_provider_malformed_response(monkeypatch):
    mock_transport(
        monkeypatch, lambda request: httpx.Response(200, content=b"not json")
    )
    with pytest.raises(GenerationError) as exc:
        generate(settings, "test", [], {})
    assert exc.value.code == "provider_response_invalid"


def test_real_ollama_answer(document):
    if os.environ.get("RAGLAB_OLLAMA_INTEGRATION") != "1":
        pytest.skip("Enable explicitly with a running Ollama model")
    response = ask(document)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["generation_performed"] and not result["abstained"]
    assert result["citations"] and "[S1]" in result["answer"]
    assert result["model_digest"] and result["token_usage"]["eval_count"] > 0
