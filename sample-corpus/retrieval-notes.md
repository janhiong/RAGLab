# RAG Lab retrieval notes

This original sample document is supplied under the CC0 1.0 public-domain dedication.

## Vector retrieval

Vector retrieval compares embeddings of a question with embeddings of document chunks. The all-MiniLM-L6-v2 model produces 384-dimensional vectors. Cosine similarity measures the angle between vectors; a higher similarity indicates closer representations, but it is not a probability of correctness.

## PostgreSQL full-text search

PostgreSQL full-text search normalizes words into lexemes and ranks matching document chunks. This baseline is lexical retrieval. PostgreSQL ts_rank_cd is not BM25. A keyword strategy can be effective for exact technical terms, but it may miss paraphrases.

## Hybrid retrieval

Reciprocal Rank Fusion (RRF) combines ranked retrieval lists using reciprocal ranks. It avoids assuming that vector similarity and keyword ranking scores have the same scale. Deduplicate matches by chunk identifier when combining lists.

## Evaluation

Recall at K is the fraction of relevant chunks present among the first K retrieved chunks. Mean reciprocal rank measures the reciprocal position of the first relevant chunk. Questions with no relevant chunks should be evaluated for abstention separately rather than given zero recall.

## Citations

A retrieval trace identifies the document, chunk, and PDF page when available. Returning relevant evidence is a retrieval result, not a generated answer. A citation identifier alone does not prove that an answer is correct or supported.
