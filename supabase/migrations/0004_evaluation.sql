BEGIN;
CREATE TABLE IF NOT EXISTS datasets (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 name text NOT NULL,
 version text NOT NULL,
 document_id uuid NOT NULL REFERENCES documents(id),
 corpus_version text NOT NULL,
 reviewed boolean NOT NULL DEFAULT false,
 questions jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(document_id, version)
);
ALTER TABLE datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS dataset_id uuid REFERENCES datasets(id);
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS completed_at timestamptz;
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS error text;
CREATE TABLE IF NOT EXISTS experiment_results (
 experiment_id uuid NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
 question_id text NOT NULL,
 status text NOT NULL CHECK(status IN ('completed','failed')),
 question jsonb NOT NULL,
 retrieval jsonb,
 answer jsonb,
 metrics jsonb NOT NULL,
 elapsed_ms double precision NOT NULL,
 error jsonb,
 review jsonb,
 PRIMARY KEY(experiment_id, question_id)
);
ALTER TABLE experiment_results ENABLE ROW LEVEL SECURITY;
COMMIT;
