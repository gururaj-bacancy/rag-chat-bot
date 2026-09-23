# Chat History Implementation Plan

**Goal:** Add multiple switchable conversation threads and a "New Chat" action, scoped entirely to chat — documents and everything else stay global.

**Architecture:** A new `conversations` table plus a `conversation_id` column on `messages`; two new endpoints (list/create conversations) and the two existing chat endpoints scoped by `conversation_id`; a small header UI in `ChatPanel` for switching.

**Tech Stack:** Same as the rest of the app — FastAPI/SQLAlchemy/Postgres backend, React/TS frontend.

**Spec:** [docs/chat-history-design.md](chat-history-design.md)

## Global Constraints

- Documents are untouched by this feature — no document-related file changes anywhere in this plan.
- No title column — a conversation's title is always derived live from its first message.
- Existing chat history must survive the migration (backfilled into one legacy conversation), not be dropped.
- No rename/delete-conversation UI — explicitly out of scope per the spec.

## Tasks

### Task 1: Conversations Schema & Models

Files: `backend/migrations/003_conversations.sql` (new — `CREATE TABLE conversations (id, created_at)`; `ALTER TABLE messages ADD COLUMN conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE`; backfill: insert one conversation row, `UPDATE messages SET conversation_id = <that id> WHERE conversation_id IS NULL`; then `ALTER TABLE messages ALTER COLUMN conversation_id SET NOT NULL`). `backend/app/db/models.py` (modify — add `Conversation(id, created_at)` model; add `conversation_id: Mapped[int]` FK column to the existing `Message` model).

Test: apply the migration against the test DB; seed a `Message` row with no `conversation_id` *before* the backfill step runs in a raw-SQL test, or (simpler) just test the end state — insert a `Conversation`, insert a `Message` pointing at it, query it back. Separately assert the migration file itself contains the backfill UPDATE (a string-contains check on the `.sql` file is fine here — the actual backfill behavior only matters for a real upgrade, not a fresh test DB).

### Task 2: Conversations API

Files: `backend/app/api/chat.py` (modify).

Add `GET /chat/conversations` → list `{id, title, created_at}` most-recent-first; `title` comes from a `DISTINCT ON (conversation_id) ... ORDER BY conversation_id, m.id ASC` query against `messages` joined to `conversations` (first 50 chars of that conversation's earliest message; `"New conversation"` if it has none). Add `POST /chat/conversations` → creates an empty `Conversation`, returns `{id, created_at}`. Modify existing `GET /chat/history` to require a `conversation_id` query param and filter by it. Modify existing `POST /chat/message` — `ChatRequest` gains a required `conversation_id: int` field; history load, the `for token in stream_agent_response(...)` call, and both `Message` inserts (user + assistant) all scope to that id instead of the whole table.

Test: `TestClient`. Create two conversations, send a message to each, assert `GET /chat/history?conversation_id=X` for one never returns the other's messages. Assert `GET /chat/conversations` returns correct derived titles and ordering. Assert `POST /chat/message` without `conversation_id` returns a 422 (FastAPI's automatic validation on the now-required field).

### Task 3: Frontend API Client

Files: `frontend/src/types.ts` (modify — add `Conversation { id: number; title: string; created_at: string }`), `frontend/src/api/client.ts` (modify — add `listConversations(): Promise<Conversation[]>` and `createConversation(): Promise<Conversation>`, both via `handleResponse` like the existing functions; change `getChatHistory(conversationId: number)` to pass it as a query param; change `streamChatMessage`'s signature to `streamChatMessage(conversationId: number, message: string, onToken, onDone, onError?)` and include `conversation_id` in the POST body).

Test: extend `frontend/src/__tests__/client.test.ts` (it already stubs `fetch` directly, per Task 17/I1's precedent) with cases for `listConversations`, `createConversation`, and that `getChatHistory`/`streamChatMessage` send the conversation id correctly.

### Task 4: Chat Panel — New Chat & History UI

Files: `frontend/src/components/ChatPanel.tsx` (modify).

On mount: call `listConversations()`; if any exist, select the most recent and load its history via `getChatHistory`; if none exist, call `createConversation()` and start empty. Store `currentConversationId` in state. Add a header row above the message list: a **"New Chat"** button (calls `createConversation`, clears `messages`, switches `currentConversationId`) and a **"History"** button that toggles a small dropdown listing conversations (title + relative time — a simple `Intl.RelativeTimeFormat` helper is fine, no new dependency), each clickable to switch. Every `streamChatMessage`/`send()` call passes `currentConversationId`.

Test: extend `frontend/src/__tests__/ChatPanel.test.tsx`. Mock `listConversations`/`createConversation`/`getChatHistory` and assert: (a) clicking "New Chat" clears the visible transcript and calls `createConversation`; (b) opening "History" and clicking a past conversation loads that conversation's messages via `getChatHistory` with the right id; (c) `streamChatMessage` is called with the currently-selected `conversation_id`.

## Self-Review

- **Spec coverage:** schema+backfill → Task 1; list/create/scoped endpoints → Task 2; client functions → Task 3; New Chat + History UI → Task 4. Out-of-scope items (rename/delete, per-conversation documents) are correctly absent from every task.
- **Type consistency:** `conversation_id` is the field name everywhere (DB column, API param/body field, frontend param) — no `conversationId`/`conv_id` drift introduced across the plan.
- **No placeholders.**
