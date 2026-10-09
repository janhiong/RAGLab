import hashlib
import os
from uuid import uuid4
import psycopg
import pytest
from fastapi.testclient import TestClient
from app.db import settings
from app.embeddings import MODEL_VERSION
from app.main import app

client = TestClient(app)


@pytest.fixture
def docs():
    if os.environ.get("RAGLAB_INTEGRATION") != "1":
        pytest.skip("Requires migrated PostgreSQL")
    ids = []
    yield ids
    with psycopg.connect(settings.database_url) as connection:
        for doc_id in ids:
            connection.execute("DELETE FROM documents WHERE id = %s", (doc_id,))


def upload(ids, text=None):
    content = text or f"Vector retrieval uses cosine similarity. PostgreSQL normalizes lexemes. {uuid4()}"
    response = client.post("/documents", files={"file": ("notes.md", content.encode())})
    assert response.status_code == 201, response.text
    doc = response.json()
    ids.append(doc["id"])
    return doc, content


def test_ingest_search_duplicate_and_provenance(docs):
    doc, content = upload(docs)
    assert doc["chunk_count"] == 1 and doc["embedding_version"] is None
    assert client.post("/documents", files={"file": ("renamed.txt", content.encode())}).status_code == 409
    response = client.post("/search", json={"question": "cosine similarity", "document_id": doc["id"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["score_type"] == "postgresql_ts_rank_cd" and body["live_generation"] is False
    assert len(body["items"]) == 1
    assert body["items"][0]["citation_id"] == body["items"][0]["id"]
    assert body["items"][0]["document_id"] == doc["id"]
    chunks = client.get(f"/documents/{doc['id']}/chunks").json()["items"]
    assert chunks[0]["metadata"]["ordinal"] == 0
    assert any(d["id"] == doc["id"] for d in client.get("/documents").json()["items"])
    assert client.post("/search", json={"question": "absentlexeme", "document_id": doc["id"]}).json()["items"] == []


def test_validation_and_document_isolation(docs):
    one, _ = upload(docs, f"Uniqueplanet is bright {uuid4()}")
    two, _ = upload(docs, f"Otherplanet is dark {uuid4()}")
    assert client.post("/search", json={"question": "Uniqueplanet", "document_id": two["id"]}).json()["items"] == []
    for payload in ({"question": " ", "document_id": one["id"]}, {"question": "test", "document_id": one["id"], "top_k": 0}):
        assert client.post("/search", json=payload).status_code == 422
    assert client.post("/search", json={"question": "test", "document_id": str(uuid4())}).status_code == 404
    assert client.post("/search", json={"question": "test", "document_id": one["id"], "strategy": "vector"}).status_code == 409


def test_read_only(monkeypatch):
    monkeypatch.setattr(settings, "private_uploads_enabled", False)
    assert client.post("/documents", files={"file": ("notes.txt", b"hello")}).status_code == 403
    assert client.post(f"/documents/{uuid4()}/index").status_code == 403


def test_missing_model_no_partial_writes(docs, monkeypatch):
    monkeypatch.setattr(settings, "embedding_model_path", "")
    content = f"model unavailable {uuid4()}".encode()
    response = client.post("/documents", data={"with_vectors": "true"}, files={"file": ("notes.txt", content)})
    assert response.status_code == 503
    with psycopg.connect(settings.database_url) as connection:
        assert connection.execute("SELECT count(*) FROM documents WHERE content_hash = %s", (hashlib.sha256(content).hexdigest(),)).fetchone()[0] == 0


def test_vector_hybrid_sql_with_test_vectors(docs, monkeypatch):
    # Deterministic test vectors verify pgvector storage/math, not actual model quality.
    monkeypatch.setattr("app.documents.embeddings", lambda texts: [[1.0] + [0.0] * 383 if "cosine" in text else [0.0, 1.0] + [0.0] * 382 for text in texts])
    doc, _ = upload(docs, "database indexes " * 100 + "cosine similarity " * 100 + str(uuid4()))
    response = client.post(f"/documents/{doc['id']}/index")
    assert response.status_code == 200, response.text
    assert response.json()["embedding_version"] == MODEL_VERSION
    for strategy in ("vector", "hybrid"):
        response = client.post("/search", json={"question": "cosine", "document_id": doc["id"], "strategy": strategy})
        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["document_id"] == doc["id"]
    response = client.post("/search", json={"question": "cosine", "document_id": doc["id"], "strategy": "vector"})
    assert response.json()["items"][0]["score"] == pytest.approx(1.0)
    assert "cosine" in response.json()["items"][0]["content"]


def test_file_validation():
    assert client.post("/documents", files={"file": ("wrong.pdf", b"broken")}).status_code == 422
    response = client.post("/documents", files={"file": ("large.txt", b"a" * (5 * 1024 * 1024 + 1))})
    assert response.status_code == 422 and "5 MiB" in response.json()["detail"]


def test_real_model_semantic_retrieval(docs):
    if os.environ.get("RAGLAB_MODEL_INTEGRATION") != "1":
        pytest.skip("Enable explicitly with the downloaded pinned embedding model")
    # Two distinct chunks: technical text and pet descriptions. This tests a paraphrase.
    database = "PostgreSQL stores relational tables and creates database indexes for SQL queries. " * 18
    pets = "Dogs and cats are friendly household pets. They provide companionship to people. " * 18
    doc, _ = upload(docs, database + pets + str(uuid4()))
    response = client.post(f"/documents/{doc['id']}/index")
    assert response.status_code == 200, response.text
    response = client.post("/search", json={"question": "Which animals make good companions?", "document_id": doc["id"], "strategy": "vector", "top_k": 1})
    assert response.status_code == 200, response.text
    assert "pets" in response.json()["items"][0]["content"]
    response = client.post("/search", json={"question": "household pets", "document_id": doc["id"], "strategy": "hybrid", "top_k": 3})
    assert response.status_code == 200, response.text
    ids = [item["id"] for item in response.json()["items"]]
    assert len(ids) == len(set(ids))
