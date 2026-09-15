# Policy Compare — RAG Chatbot Design

## Overview

A standalone RAG chatbot that helps people understand and verify their Indian
health insurance (mediclaim) claim settlements. A user uploads three kinds of
documents for a single claim — the hospital's final bill, their mediclaim
policy, and the TPA/insurer's claim settlement letter — and chats with the
system to understand why deductions happened and whether the insurer's math
actually matches what the policy says.

This is the assignment deliverable: an end-to-end RAG system demonstrating
the complete pipeline (upload → parse → chunk → embed → retrieve →
generate), built to go beyond a basic chat-with-a-document demo.

## Goals

- Demonstrate a complete, production-oriented RAG pipeline.
- Go beyond retrieval-only RAG by adding a deterministic reconciliation
  engine that checks the insurer's settlement math against the policy's
  actual rules — the thing a pure vector-search chatbot cannot do.
- Ground every answer in citations back to the source document (page/clause
  for the policy, line item for the bill/settlement letter).
- Preserve multi-turn chat history across sessions.
- Support document upload and deletion, with deleted documents fully
  excluded from all future answers and reconciliation.

## Non-Goals

- No live external data source or dependency on another running system.
- No multi-user auth/tenancy — single-user, single-workspace scope.
- No integration with real insurer/TPA systems — synthetic sample documents,
  authored to look like realistic Indian mediclaim paperwork.
- No WhatsApp/Slack interface — a web chat UI only.
- No support for more than one active document per type at a time (see
  Assumptions).

## Domain Model

Three document types, uploaded per claim:

1. **Hospital final bill** — itemized: room rent/day, OT charges, doctor
   fees, medicines, consumables, diagnostics, nursing, misc charges.
2. **Mediclaim policy** — narrative + tabular: sum insured, room rent
   limit/category, co-pay %, sub-limits (e.g. cataract, specific
   procedures), exclusions, waiting periods, reference to the non-payable
   items list.
3. **Claim settlement letter** (TPA or insurer) — claimed vs. approved vs.
   deducted amounts, with deduction reason codes.

## Assumptions

- **PDF only for the MVP.** Scanned/image-based documents (OCR) are a
  stretch item, not required for the core pipeline to work.
- **At most one active document per type.** Reconciliation assumes exactly
  one bill, one policy, and one settlement letter. Uploading a new document
  of a type that already exists does **not** auto-replace the old one —
  the user must delete the existing one first. This avoids ambiguity in
  which bill a settlement letter is being reconciled against.

## Architecture

**Components**

- FastAPI backend (Python)
- React (Vite, TypeScript) frontend — chat UI + document management sidebar
- Postgres + pgvector (Docker Compose) — vector embeddings, full-text index
  (for hybrid search), document metadata, extracted structured records, and
  chat history, all in one datastore
- Voyage AI — embeddings
- Claude Opus 5 — the chat agent (adaptive thinking, tool use, native
  citations)
- Claude Haiku 4.5 — cheap tasks: structured extraction from bills/
  settlement letters, contextual chunk blurbs for the policy document

**Ingestion**

1. User uploads a PDF via the UI, tagged by document type.
2. Layout-aware parsing (PyMuPDF) preserves page number and position so
   citations can point back to an exact location.
3. **Policy documents** are chunked on heading boundaries. Each chunk gets a
   short Haiku-generated blurb situating it within the document (Anthropic's
   contextual retrieval technique) prepended before embedding. Chunks are
   embedded (Voyage) and indexed for both vector similarity and full-text
   search.
4. **Bill and settlement letter** go through a structured-extraction pass
   (Claude Haiku with structured outputs) into line-item records — item,
   amount, category, date — stored as structured rows in Postgres. The raw
   text is also chunked and indexed identically to the policy, so line items
   remain citable in chat even outside of a reconciliation call.

**Chat & Retrieval**

The agent (Claude Opus 5) has two tools:

- `search_docs(query)` — hybrid retrieval (dense pgvector cosine + Postgres
  full-text/BM25, fused via Reciprocal Rank Fusion) over indexed chunks,
  returning top-k results with citations.
- `reconcile_claim()` — a **deterministic** function, not an LLM guess. It
  takes the extracted bill line items, the policy's extracted limits (room
  rent cap, co-pay %, sub-limits), and the settlement letter's actual
  claimed/approved/deducted figures; computes what the settlement *should*
  be (including the room-rent-proportionate-deduction calculation, where
  exceeding the room rent cap also proportionately reduces other charges);
  and diffs that against what the settlement letter actually shows. Returns
  a structured discrepancy report with every figure traceable to its source
  document.

The agent decides per-question which tool(s) to call, and can call
`search_docs` more than once for multi-hop questions.

Responses stream to the UI with citations rendered inline. When neither
tool can ground an answer — a scenario the policy doesn't address, or a
deduction the settlement letter doesn't explain — the agent says so
explicitly (e.g. "your policy doesn't specify a sub-limit for this
procedure, so I can't verify this deduction — you'd need to raise this with
the insurer directly") rather than guessing.

**Chat History**

- Persisted in Postgres (a `messages` table), reloaded on page load so
  history survives a refresh or a later visit.
- Prior turns are included in the agent's context (with prompt caching on
  the stable prefix) so multi-turn follow-ups work.
- Follow-up questions are rewritten against history into a standalone query
  before retrieval, so "what about the room rent one?" resolves correctly.
- Deleting a document does not rewrite or remove past chat messages — they
  remain as a historical log. It only affects what gets retrieved or
  reconciled going forward.

**Document Management**

- A `documents` table tracks id, type, filename, upload timestamp, and
  indexing status.
- Deleting a document removes its chunks, embeddings, and any structured
  records from the index and from `reconcile_claim`'s inputs. Nothing
  currently indexed can reference a deleted document again.

## Trust & Honesty

- Reconciliation output always shows its inputs (which number came from
  which document) so the result is independently checkable, not a black
  box.
- Explicit abstention is a distinct, first-class response — separate from
  "the numbers check out" — whenever the documents don't cover a question.
- Citations use Claude's native citations feature, which returns exact
  cited text and location rather than model-invented reference markers.

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI |
| Frontend | React + Vite, TypeScript |
| Database | Postgres 16 + pgvector, via Docker Compose |
| Embeddings | Voyage AI |
| LLM (agent) | Claude Opus 5, adaptive thinking |
| LLM (cheap tasks) | Claude Haiku 4.5 |
| PDF parsing | PyMuPDF |
| Agent orchestration | Anthropic Tool Runner |

## Sample Data

Since there is no real claim data to ingest, synthetic sample documents are
part of the deliverable: a handful of realistic hospital bills, mediclaim
policies, and settlement letters modeled on real Indian insurer formats,
including intentionally planted discrepancies (e.g. an incorrectly computed
room-rent-proportionate deduction) so the reconciliation engine has
something real to catch.

## Testing / Eval (stretch, lower priority)

- A small golden set of questions per sample claim with expected
  answers/citations.
- Reconciliation correctness checked against manually computed expected
  settlements for each synthetic case.

## Open Risks

- **Parsing quality** on messy or inconsistently formatted itemized bills —
  mitigated by keeping OCR/scanned-document support out of MVP scope.
- **Extraction accuracy** for unusual bill layouts — if this proves
  unreliable in practice, a human-reviewable extraction step in the UI is a
  reasonable stretch fallback, not required for MVP.
- **Domain rule fidelity** — the room-rent-proportionate-deduction formula
  and sub-limit rules will be implemented against IRDAI-published standard
  practice as the reference for correctness.
