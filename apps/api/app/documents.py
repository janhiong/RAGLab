import hashlib
from time import perf_counter
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from app.db import connect, settings
from app.embeddings import EmbeddingsUnavailable, MODEL_VERSION, embed, vector_literal
from app.ingestion.parsing import (
    CHUNK_VERSION,
    MAX_UPLOAD_BYTES,
    InvalidDocument,
    chunk_pages,
    parse_document,
)
from app.retrieval import reciprocal_rank_fusion
from app.providers.ollama import generation_status

router = APIRouter()
DOCUMENT_FIELDS = "id, filename, status, corpus_version, chunking_version, embedding_version, chunk_count, created_at"


def database_error():
    return HTTPException(status_code=503, detail="Database or migration unavailable")


def embeddings(texts):
    try:
        return embed(texts, settings.embedding_model_path)
    except EmbeddingsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.get("/capabilities")
def capabilities():
    generation = generation_status(settings)
    return {
        "private_uploads_enabled": settings.private_uploads_enabled,
        "embedding_model_configured": bool(settings.embedding_model_path),
        "embedding_version": MODEL_VERSION,
        "live_generation": generation["available"],
        "generation": generation,
    }


@router.post("/documents", status_code=201)
def upload_document(file: UploadFile = File(...), with_vectors: bool = Form(False)):
    if not settings.private_uploads_enabled:
        raise HTTPException(
            status_code=403, detail="Uploads are disabled in read-only mode."
        )
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1][:200]
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    try:
        chunks = chunk_pages(parse_document(filename, data))
    except InvalidDocument as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    content_hash = hashlib.sha256(data).hexdigest()
    # Check duplicates before expensive inference; UNIQUE also handles concurrent uploads.
    try:
        with connect() as connection:
            existing = connection.execute(
                "SELECT id FROM documents WHERE content_hash = %s", (content_hash,)
            ).fetchone()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail="This file is already indexed. Use its existing document.",
                )
    except psycopg.Error:
        raise database_error() from None
    vectors = embeddings([chunk.content for chunk in chunks]) if with_vectors else None
    corpus_version = hashlib.sha256(
        f"{content_hash}:{CHUNK_VERSION}".encode()
    ).hexdigest()
    try:
        with connect() as connection:
            doc = connection.execute(
                f"INSERT INTO documents (filename, content_hash, status, corpus_version, chunking_version, embedding_version, chunk_count) VALUES (%s, %s, 'indexed', %s, %s, %s, %s) RETURNING {DOCUMENT_FIELDS}",
                (
                    filename,
                    content_hash,
                    corpus_version,
                    CHUNK_VERSION,
                    MODEL_VERSION if vectors else None,
                    len(chunks),
                ),
            ).fetchone()
            for index, chunk in enumerate(chunks):
                connection.execute(
                    "INSERT INTO chunks (document_id, content, page, embedding, metadata) VALUES (%s, %s, %s, %s::vector, %s)",
                    (
                        doc["id"],
                        chunk.content,
                        chunk.page,
                        vector_literal(vectors[index]) if vectors else None,
                        Jsonb(
                            {
                                "ordinal": chunk.ordinal,
                                "chunking_version": CHUNK_VERSION,
                                "embedding_version": MODEL_VERSION if vectors else None,
                            }
                        ),
                    ),
                )
            return doc
    except psycopg.errors.UniqueViolation:
        raise HTTPException(
            status_code=409, detail="This file is already indexed."
        ) from None
    except psycopg.Error:
        raise database_error() from None


@router.get("/documents")
def documents(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    try:
        with connect() as connection:
            total = connection.execute(
                "SELECT count(*) AS count FROM documents"
            ).fetchone()["count"]
            items = connection.execute(
                f"SELECT {DOCUMENT_FIELDS} FROM documents ORDER BY created_at DESC, id LIMIT %s OFFSET %s",
                (limit, offset),
            ).fetchall()
            return {"items": items, "total": total}
    except psycopg.Error:
        raise database_error() from None


@router.get("/documents/{document_id}/chunks")
def document_chunks(
    document_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    try:
        with connect() as connection:
            if not connection.execute(
                "SELECT id FROM documents WHERE id = %s", (document_id,)
            ).fetchone():
                raise HTTPException(status_code=404, detail="Document not found")
            items = connection.execute(
                "SELECT id, document_id, content, page, metadata FROM chunks WHERE document_id = %s ORDER BY (metadata->>'ordinal')::int, id LIMIT %s OFFSET %s",
                (document_id, limit, offset),
            ).fetchall()
            return {"items": items}
    except psycopg.Error:
        raise database_error() from None


@router.post("/documents/{document_id}/index")
def index_vectors(document_id: UUID):
    if not settings.private_uploads_enabled:
        raise HTTPException(
            status_code=403, detail="Indexing is disabled in read-only mode."
        )
    try:
        with connect() as connection:
            doc = connection.execute(
                "SELECT id FROM documents WHERE id = %s", (document_id,)
            ).fetchone()
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found")
            chunks = connection.execute(
                "SELECT id, content FROM chunks WHERE document_id = %s ORDER BY (metadata->>'ordinal')::int, id",
                (document_id,),
            ).fetchall()
        vectors = embeddings([chunk["content"] for chunk in chunks])
        with connect() as connection:
            for chunk, vector in zip(chunks, vectors, strict=True):
                connection.execute(
                    "UPDATE chunks SET embedding = %s::vector, metadata = metadata || %s WHERE id = %s",
                    (
                        vector_literal(vector),
                        Jsonb({"embedding_version": MODEL_VERSION}),
                        chunk["id"],
                    ),
                )
            connection.execute(
                "UPDATE documents SET embedding_version = %s WHERE id = %s",
                (MODEL_VERSION, document_id),
            )
        return {
            "id": document_id,
            "embedding_version": MODEL_VERSION,
            "chunk_count": len(chunks),
        }
    except psycopg.Error:
        raise database_error() from None


class SearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    document_id: UUID
    strategy: Literal["keyword", "vector", "hybrid"] = "keyword"
    top_k: int = Field(default=5, ge=1, le=20)
    keyword_mode: Literal["websearch", "any_term"] = "websearch"


@router.post("/search")
def search(request: SearchRequest):
    started = perf_counter()
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="Enter a nonempty question.")
    try:
        with connect() as connection:
            doc = connection.execute(
                "SELECT filename, embedding_version, corpus_version, chunking_version FROM documents WHERE id = %s",
                (request.document_id,),
            ).fetchone()
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found")
            limit = request.top_k * 4 if request.strategy == "hybrid" else request.top_k
            keyword = []
            vector = []
            if request.strategy in ("keyword", "hybrid"):
                query_expression = "websearch_to_tsquery('english', %s)"
                if request.keyword_mode == "any_term":
                    query_expression = "to_tsquery('english', (SELECT string_agg(quote_literal(term), ' | ') FROM unnest(tsvector_to_array(to_tsvector('english', %s))) AS term))"
                keyword = connection.execute(
                    f"SELECT id, document_id, content, page, ts_rank_cd(search_vector, {query_expression}) AS score FROM chunks WHERE document_id = %s AND search_vector @@ {query_expression} ORDER BY score DESC, id LIMIT %s",
                    (request.question, request.document_id, request.question, limit),
                ).fetchall()
            if request.strategy in ("vector", "hybrid"):
                if doc["embedding_version"] != MODEL_VERSION:
                    raise HTTPException(
                        status_code=409,
                        detail="This document needs vector indexing with the configured model first.",
                    )
                query_vector = vector_literal(embeddings([request.question])[0])
                vector = connection.execute(
                    "SELECT id, document_id, content, page, 1 - (embedding <=> %s::vector) AS score FROM chunks WHERE document_id = %s AND embedding IS NOT NULL ORDER BY embedding <=> %s::vector, id LIMIT %s",
                    (query_vector, request.document_id, query_vector, limit),
                ).fetchall()
            items = (
                reciprocal_rank_fusion([keyword, vector], request.top_k)
                if request.strategy == "hybrid"
                else keyword if request.strategy == "keyword" else vector
            )
            for rank, item in enumerate(items, 1):
                item.update(
                    rank=rank, filename=doc["filename"], citation_id=str(item["id"])
                )
            return {
                "question": request.question,
                "strategy": request.strategy,
                "top_k": request.top_k,
                "keyword_mode": request.keyword_mode,
                "corpus_version": doc["corpus_version"],
                "chunking_version": doc["chunking_version"],
                "embedding_version": (
                    doc["embedding_version"] if request.strategy != "keyword" else None
                ),
                "score_type": {
                    "keyword": "postgresql_ts_rank_cd",
                    "vector": "cosine_similarity",
                    "hybrid": "rrf",
                }[request.strategy],
                "items": items,
                "retrieval_ms": round((perf_counter() - started) * 1000, 2),
                "live_generation": False,
            }
    except psycopg.Error:
        raise database_error() from None
