import os

import psycopg
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_generation_unavailable():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["live_generation"] is False


def test_database_failure_is_explicit(monkeypatch):
    def unavailable():
        raise psycopg.OperationalError("private connection details")
    monkeypatch.setattr("app.main.connect", unavailable)
    for route in ("/ready", "/overview", "/experiments"):
        response = client.get(route)
        assert response.status_code == 503
        assert "private" not in response.text


def test_cors_allows_local_frontend():
    response = client.options("/overview", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_database_integration():
    if os.environ.get("RAGLAB_INTEGRATION") != "1":
        import pytest
        pytest.skip("Set RAGLAB_INTEGRATION=1 with a migrated database")
    assert client.get("/ready").status_code == 200
    response = client.get("/overview")
    assert response.status_code == 200
    assert isinstance(response.json()["documents"], int)
    assert isinstance(response.json()["experiments"], int)
    assert client.get("/experiments").status_code == 200


def test_persisted_experiment_is_visible():
    if os.environ.get("RAGLAB_INTEGRATION") != "1":
        import pytest
        pytest.skip("Requires migrated database")
    from app.main import settings
    with psycopg.connect(settings.database_url) as connection:
        run_id = connection.execute(
            "INSERT INTO experiments (name, configuration, corpus_version, dataset_version) VALUES (%s, %s, %s, %s) RETURNING id",
            ("Integration test", "{}", "test-v1", "test-v1"),
        ).fetchone()[0]
    try:
        response = client.get("/experiments")
        assert response.status_code == 200
        assert any(run["id"] == str(run_id) and run["status"] == "queued" for run in response.json()["items"])
        assert client.get("/overview").json()["experiments"] >= 1
    finally:
        with psycopg.connect(settings.database_url) as connection:
            connection.execute("DELETE FROM experiments WHERE id = %s", (run_id,))
