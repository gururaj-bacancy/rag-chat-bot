# Database Schema Reference

Postgres + pgvector is the single datastore for everything: vector embeddings, full-text search, extracted structured numbers, document metadata, and chat history. This doc explains what each table and column is for. See [`backend/migrations/`](../backend/migrations/) for the exact DDL and [`docs/design.md`](design.md) for the broader architecture.

## `documents`

One row per uploaded PDF (`bill` / `policy` / `settlement`). At most one active (non-`failed`) document per type.

| Column | Type | Significance |
|---|---|---|
| `id` | serial PK | Referenced by `chunks`, `line_items`, `policy_rules` — all cascade-delete when a document is deleted. |
| `doc_type` | varchar, checked `bill`/`policy`/`settlement` | Routes ingestion: `policy` gets chunked + rule-extracted, `bill`/`settlement` get chunked + line-item-extracted. Also what the "one active document per type" constraint checks. |
| `filename` | varchar | Display only — shown in the UI sidebar and in resolved chat citations. |
| `status` | varchar, checked `processing`/`indexed`/`failed` | A `failed` document doesn't block re-uploading that type (the duplicate check filters `status != 'failed'`). |
| `uploaded_at` | timestamptz | Sort key for `GET /documents` (oldest-first). |
| `room_rent_per_day` | numeric, nullable | Extracted from a **bill** only. `reconcile_claim` needs this as a number to compute the room-rent-proportionate deduction without assuming a fixed stay length. |
| `settlement_total_claimed` / `_approved` / `_deducted` | numeric, nullable | Extracted from a **settlement letter** only. Most real letters print just these three totals with no line-item table — this lets reconciliation compare actual vs. correct approval even when there's nothing to sum from `line_items`. |

## `chunks`

One row per text chunk, from every document type (not just policy — bill/settlement line items stay individually citable in chat too). This is the hybrid-search index.

| Column | Type | Significance |
|---|---|---|
| `id` | serial PK | What a `[[chunk_id]]` citation marker in the agent's output resolves against. |
| `document_id` | FK, cascade delete | Ties the chunk to its source document for citation metadata. |
| `chunk_text` | text | The raw source text — what gets quoted and what `search_vector` indexes. |
| `contextual_text` | text | `chunk_text` prepended with a Haiku-generated situating blurb (Anthropic's contextual retrieval technique). This is what actually gets embedded, so a terse chunk like "TOTAL BILL AMOUNT: Rs 1,20,000" still embeds with enough context to be retrieved by a relevant query. |
| `page_number` | integer, nullable | From PyMuPDF's layout-aware parse — lets a citation point at an exact page. |
| `embedding` | `vector(1024)` | Voyage `voyage-4-large` embedding of `contextual_text`. HNSW cosine index — the dense half of hybrid search. |
| `search_vector` | `tsvector` | Full-text index over `chunk_text`, built in a second pass after insert. GIN index — the sparse half of hybrid search, fused with vector results via Reciprocal Rank Fusion. |
| `created_at` | timestamptz | Bookkeeping only. |

## `line_items`

One table, two shapes depending on which columns are filled: `category` for bill rows, `claimed_amount`/`approved_amount`/`deducted_amount`/`deduction_reason` for settlement rows.

| Column | Type | Significance |
|---|---|---|
| `id` | serial PK | — |
| `document_id` | FK, cascade delete | Which bill or settlement this line belongs to. |
| `description` | text | Free-text label from extraction — shown in answers/citations, not parsed further. |
| `category` | varchar | **Bill rows only.** One of `room_rent`/`ot_charges`/`doctor_fees`/`nursing`/`medicines`/`consumables`/`diagnostics`/`misc`. Shared vocabulary with `policy_rules.sub_limits` keys and with the reconciliation rules' proportionate-vs-exempt split (room_rent/ot/doctor/nursing get the room-rent-ratio deduction; medicines/consumables/diagnostics are exempt). A naming drift here silently breaks reconciliation math. |
| `amount` | numeric, not null | The bill line's value. For a settlement row this duplicates `claimed_amount` to satisfy the shared NOT NULL constraint. |
| `claimed_amount` / `approved_amount` / `deducted_amount` | numeric, nullable | **Settlement rows only** — the letter's own stated figures for a line, when it itemizes at all. |
| `deduction_reason` | text, nullable | **Settlement rows only** — the insurer's stated justification, surfaced in chat answers explaining *why* a deduction happened (separate from whether reconciliation agrees it was computed correctly). |

## `policy_rules`

One row per policy document — the numeric terms `reconcile_claim` needs to recompute a settlement.

| Column | Type | Significance |
|---|---|---|
| `id` | serial PK | — |
| `document_id` | FK, cascade delete | One row per active policy. |
| `sum_insured` | numeric, not null | The policy's coverage ceiling. |
| `room_rent_limit_per_day` | numeric, nullable | The cap that triggers the proportionate-deduction calculation when actual room rent (`documents.room_rent_per_day`) exceeds it. |
| `room_rent_limit_type` | varchar: `fixed_amount` / `percentage_of_sum_insured` / `no_limit` | How to interpret `room_rent_limit_per_day`. The proportionate-ratio calculation only applies when this is `fixed_amount`. |
| `co_pay_percentage` | numeric(5,2), default 0 | Applied *after* the room-rent deduction, on whatever remains — order matters for getting the correct final figure. |
| `sub_limits` | jsonb, default `{}` | Optional per-category caps, keyed by the same `category` vocabulary as `line_items`. Empty means no sub-limits apply. |

## `conversations`

| Column | Type | Significance |
|---|---|---|
| `id` | serial PK | What every message and both chat endpoints scope to. |
| `created_at` | timestamptz | Sorts the History dropdown most-recent-first and drives its relative-time display ("2 hours ago"). There is deliberately no `title` column — a conversation's title is always derived live from its first message. |

## `messages`

| Column | Type | Significance |
|---|---|---|
| `id` | serial PK | — |
| `role` | varchar, checked `user`/`assistant` | Which side of the transcript a message renders on, and whether it's replayed as a turn in the agent's history. |
| `content` | text | The **cleaned** text — citation markers already resolved from `[[chunk_id]]` to `[1]`/`[2]`, never raw model output. |
| `citations` | jsonb, nullable | List of `{number, chunk_id, doc_type, filename, page_number}` objects, captured at the moment the assistant's turn is persisted — so a citation stays resolvable even if its source chunk or document is later deleted. |
| `created_at` | timestamptz | Chat history's chronological order. |
| `conversation_id` | FK, cascade delete | Scopes the message to its thread. Deleting a conversation (not currently exposed in the UI) would cascade-delete its messages. |

## How the tables connect

`documents` → `chunks` feeds hybrid search (the `search_docs` tool). `documents` + `line_items` + `policy_rules` feed the deterministic reconciliation engine (the `reconcile_claim` tool) — plain arithmetic, not an LLM guess. `conversations` + `messages` are entirely independent of the document tables: switching or creating a conversation never touches ingested document data.
