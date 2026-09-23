-- Covers both GET /chat/history?conversation_id=... (filters + orders by id)
-- and the derived-title LEFT JOIN LATERAL subquery in GET /chat/conversations
-- (filters by conversation_id, orders by id, LIMIT 1) — both currently seq-scan
-- messages per conversation.
CREATE INDEX IF NOT EXISTS messages_conversation_id_idx ON messages (conversation_id, id);
