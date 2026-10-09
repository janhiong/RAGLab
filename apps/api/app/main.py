import logging

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row

from app.config import Settings

logger = logging.getLogger(__name__)
settings = Settings()
app = FastAPI(title="RAG Lab API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def connect():
    return psycopg.connect(settings.database_url, connect_timeout=3, row_factory=dict_row)


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0", "live_generation": False}


@app.get("/ready")
def ready():
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                extension = cursor.fetchone()
                cursor.execute("SELECT count(*) AS count FROM documents")
                cursor.fetchone()
                cursor.execute("SELECT count(*) AS count FROM experiments")
                cursor.fetchone()
                if extension is None:
                    raise RuntimeError("pgvector extension is missing")
    except (psycopg.Error, RuntimeError):
        logger.warning("Database readiness check failed")
        raise HTTPException(status_code=503, detail="Database or migration unavailable") from None
    return {"status": "ready", "database": "connected", "pgvector": extension["extversion"]}


@app.get("/overview")
def overview():
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) AS count FROM documents")
                documents = cursor.fetchone()["count"]
                cursor.execute("SELECT count(*) AS count FROM experiments")
                experiments = cursor.fetchone()["count"]
    except psycopg.Error:
        raise HTTPException(status_code=503, detail="Database or migration unavailable") from None
    return {"documents": documents, "experiments": experiments, "live_generation": False}


@app.get("/experiments")
def experiments():
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, name, status, created_at FROM experiments ORDER BY created_at DESC LIMIT 100")
                return {"items": cursor.fetchall()}
    except psycopg.Error:
        raise HTTPException(status_code=503, detail="Database or migration unavailable") from None
