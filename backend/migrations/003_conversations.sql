CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE messages ADD COLUMN IF NOT EXISTS conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE;

DO $$
DECLARE
    legacy_id INTEGER;
BEGIN
    IF EXISTS (SELECT 1 FROM messages WHERE conversation_id IS NULL) THEN
        INSERT INTO conversations DEFAULT VALUES RETURNING id INTO legacy_id;
        UPDATE messages SET conversation_id = legacy_id WHERE conversation_id IS NULL;
    END IF;
END $$;

ALTER TABLE messages ALTER COLUMN conversation_id SET NOT NULL;
