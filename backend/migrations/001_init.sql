CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    doc_type VARCHAR(20) NOT NULL CHECK (doc_type IN ('bill', 'policy', 'settlement')),
    filename VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processing' CHECK (status IN ('processing', 'indexed', 'failed')),
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    contextual_text TEXT NOT NULL,
    page_number INTEGER,
    embedding vector(1024),
    search_vector TSVECTOR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_search_vector_idx ON chunks USING GIN (search_vector);

CREATE TABLE IF NOT EXISTS line_items (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    category VARCHAR(30) NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    claimed_amount NUMERIC(12,2),
    approved_amount NUMERIC(12,2),
    deducted_amount NUMERIC(12,2),
    deduction_reason TEXT
);

CREATE TABLE IF NOT EXISTS policy_rules (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    sum_insured NUMERIC(12,2) NOT NULL,
    room_rent_limit_per_day NUMERIC(12,2),
    room_rent_limit_type VARCHAR(30) NOT NULL,
    co_pay_percentage NUMERIC(5,2) NOT NULL DEFAULT 0,
    sub_limits JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    role VARCHAR(10) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    citations JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
