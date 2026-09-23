# Chat History & New Chat — Design

## Overview

ClaimAudit currently has exactly one global, continuous conversation — every message ever sent lives in one flat `messages` table with no way to start over or switch between past conversations. This adds multiple conversation threads, a "New Chat" action, and a history list to switch between them — same pattern as Claude Code's session picker.

**Documents are unaffected.** The uploaded bill/policy/settlement stay exactly as they are across every conversation; only the chat thread resets. This is a deliberate scope boundary, not an oversight — multi-document-set support is a different, larger feature.

## Data Model

New table:

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`messages` gets one new column:

```sql
ALTER TABLE messages ADD COLUMN IF NOT EXISTS conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE;
```

**Migrating existing data:** the same migration inserts one `conversations` row and backfills every pre-existing `messages` row with `NULL` conversation_id to point at it, so no chat history already in the database is lost or orphaned. After the backfill, `conversation_id` gets a `NOT NULL` constraint — every message from this point on must belong to a conversation.

No title column. A conversation's title is derived, not stored: the first ~50 characters of its first user message (or "New conversation" if it has no messages yet).

## API Changes

- `GET /chat/conversations` — list all conversations, most recent first, each as `{id, title, created_at}` where `title` is computed via a `DISTINCT ON (conversation_id) ... ORDER BY conversation_id, id ASC` query joined against `messages`.
- `POST /chat/conversations` — create a new (empty) conversation, return its `{id, created_at}`. This is what "New Chat" calls.
- `GET /chat/history?conversation_id={id}` — existing endpoint, now scoped by a required query param instead of returning the entire table.
- `POST /chat/message` — existing endpoint, request body gains a required `conversation_id` field; history is loaded and the new messages are persisted scoped to that conversation instead of globally.

## Frontend

A small header row inside `ChatPanel`, above the message list:
- **`+ New Chat`** button — calls `POST /chat/conversations`, clears the visible message list, switches `currentConversationId` to the new id.
- **`History`** dropdown/button — on click, calls `GET /chat/conversations` and shows a simple list (title + relative time, e.g. "2 hours ago"); clicking an entry calls `GET /chat/history?conversation_id=...`, replaces the message list, and switches `currentConversationId`.

On mount, `ChatPanel` calls `GET /chat/conversations`: if any exist, it opens the most recent one; if none exist (fresh install), it creates one via `POST /chat/conversations` and opens that. Every `streamChatMessage`/`getChatHistory` call from here on carries the active `conversation_id`.

Document sidebar (`DocumentSidebar`) is untouched — this feature is scoped entirely to the chat panel and the `messages`/`conversations` tables.

## Out of scope

Renaming a conversation, deleting a conversation, and per-conversation document sets are all explicitly not part of this — same "smallest thing that's actually useful" reasoning as the rest of this project. Easy to add later if it turns out to matter.
