import logging

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.db import connect, settings
from app.documents import router as documents_router
from app.generation import router as generation_router
from app.providers.ollama import generation_status

logger = logging.getLogger(__name__)
app = FastAPI(title="RAG Lab API", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "0.3.0",
        "generation_enabled": settings.generation_enabled,
    }


@app.get("/ready")
def ready():
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
                )
                extension = cursor.fetchone()
                cursor.execute(
                    "SELECT chunk_count, embedding_version FROM documents LIMIT 0"
                )
                cursor.fetchall()
                cursor.execute("SELECT count(*) AS count FROM experiments")
                cursor.fetchone()
                cursor.execute("SELECT id FROM query_traces LIMIT 0")
                if extension is None:
                    raise RuntimeError("pgvector extension is missing")
    except (psycopg.Error, RuntimeError):
        logger.warning("Database readiness check failed")
        raise HTTPException(
            status_code=503, detail="Database or migration unavailable"
        ) from None
    return {
        "status": "ready",
        "database": "connected",
        "pgvector": extension["extversion"],
    }


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
        raise HTTPException(
            status_code=503, detail="Database or migration unavailable"
        ) from None
    return {
        "documents": documents,
        "experiments": experiments,
        "live_generation": generation_status(settings)["available"],
    }


@app.get("/experiments")
def experiments():
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, name, status, created_at FROM experiments ORDER BY created_at DESC LIMIT 100"
                )
                return {"items": cursor.fetchall()}
    except psycopg.Error:
        raise HTTPException(
            status_code=503, detail="Database or migration unavailable"
        ) from None


app.include_router(documents_router)

app.include_router(generation_router)
