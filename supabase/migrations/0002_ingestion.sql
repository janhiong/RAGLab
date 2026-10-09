BEGIN;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunking_version text NOT NULL DEFAULT 'legacy';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding_version text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_count integer NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks(document_id);
COMMIT;
