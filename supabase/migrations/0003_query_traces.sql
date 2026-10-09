BEGIN;
CREATE TABLE IF NOT EXISTS query_traces (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid REFERENCES documents(id) ON DELETE CASCADE,
    question text NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    configuration jsonb NOT NULL,
    retrieval jsonb,
    context jsonb,
    result jsonb,
    error jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS query_traces_document_idx ON query_traces(document_id);
ALTER TABLE query_traces ENABLE ROW LEVEL SECURITY;
COMMIT;
