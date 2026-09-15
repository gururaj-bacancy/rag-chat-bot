# Policy Compare Implementation Plan

**Goal:** RAG chatbot that ingests a hospital bill, mediclaim policy, and claim settlement letter, then answers questions using hybrid document retrieval plus a deterministic reconciliation engine that recomputes the settlement and flags mismatches.

**Architecture:** FastAPI backend (ingestion → Postgres+pgvector → Claude Opus 5 agent with two tools) + React chat frontend with document upload/delete. Chat history persists in Postgres.

**Tech Stack:** Python/FastAPI, SQLAlchemy+psycopg3, Postgres+pgvector, Voyage AI (`voyage-4-large`) embeddings, Claude Opus 5 (agent) + Haiku 4.5 (extraction), PyMuPDF, React+Vite+TS, Docker Compose.

**Spec:** [docs/design.md](design.md)

## Global Constraints

- PDF only, no OCR for MVP.
- At most one active document per type (`bill`/`policy`/`settlement`) — reject duplicate uploads until the existing one is deleted.
- No auth/multi-tenancy — single global workspace, single conversation.
- Deleting a document cascades out of retrieval and reconciliation; past chat messages are never rewritten.
- Money values in INR, rounded to 2 decimals for display.
- Citations are our own chunk metadata (page, document, chunk id), not Claude's native `citations` block feature — that's built for whole documents in a request, not agentically-retrieved tool results.
- Backend routes are sync `def` — every client (SQLAlchemy, Anthropic SDK, Voyage SDK, PyMuPDF) is sync.

## Decisions Made Beyond the Spec

- **Policy documents also get structured extraction** (room rent limit, co-pay %, sub-limits), not just narrative chunking — `reconcile_claim` needs these as numbers, which the spec implied but didn't say explicitly.
- **No separate query-rewriting step.** The agent already sees full chat history each turn, so its system prompt just instructs it to always pass `search_docs` a standalone, context-complete query — a bolted-on rewrite call would be redundant.
- **Citations as numbered footnotes, resolved server-side.** Agent marks sources inline as `[[chunk_id]]`; the chat API resolves each to `{document, page, doc_type}`, renumbers as `[1]`, `[2]`... in order of first appearance, and returns a `citations` array — frontend does no parsing.

## Reference: Demo Reconciliation Numbers

Used consistently across ingestion, reconciliation, and sample-data tasks so tests and manual verification agree:

Sum insured ₹5,00,000 · room rent limit ₹5,000/day · room rent charged ₹8,000/day × 5 days · co-pay 10%. Bill: room rent ₹40,000, OT ₹30,000, doctor ₹15,000, nursing ₹10,000 (proportionate-deduction categories, sum ₹95,000) + medicines ₹12,000, consumables ₹8,000, diagnostics ₹5,000 (exempt). Ratio = 5000/8000 = 0.625 → room-rent deduction ₹35,625 → admissible before co-pay ₹84,375 → co-pay deduction ₹8,437.50 → **correct approved amount ₹75,937.50**. Planted-wrong settlement letter shows ₹70,000 approved → discrepancy **₹5,937.50**.

## Tasks

1. **Project scaffolding** — `docker-compose.yml` (Postgres+pgvector), `backend/app/main.py` + `config.py`, `.env.example`, `requirements.txt`. FastAPI skeleton with `/health`. Test: health check returns 200.

2. **Database schema & connection** — `backend/migrations/001_init.sql` (documents, chunks, line_items, policy_rules, messages; pgvector + tsvector columns), SQLAlchemy models in `app/db/models.py`, migration runner, test-DB fixture in `conftest.py`. Test: insert/query round trip per table.

3. **PDF parsing** — `app/ingestion/pdf_parser.py`: `parse_pdf(path) -> list[TextBlock]` (text + 1-indexed page number) via PyMuPDF. Test: generated 2-page PDF returns correct per-page text.

4. **Policy chunker** — `app/ingestion/chunker.py`: `chunk_policy_blocks(blocks) -> list[Chunk]`, splits on short-all-caps heading lines. Test: heading-delimited blocks produce the right chunk boundaries.

5. **Voyage embeddings client** — `app/ingestion/embeddings.py`: `embed_documents(texts)` / `embed_query(text)` wrapping `voyageai.Client.embed`, `input_type="document"` vs `"query"`. Test: mocked client called with correct model/input_type.

6. **Contextual blurb generator** — `app/ingestion/contextual.py`: `generate_contextual_text(chunk_text, document_summary) -> str`, one Haiku call producing a situating blurb prepended to the chunk (Anthropic's contextual retrieval technique). Test: mocked Haiku response, blurb + chunk concatenated correctly.

7. **Bill/settlement structured extraction** — `app/ingestion/extraction.py`: Pydantic `BillExtraction`/`SettlementExtraction` (+ line item models), `extract_bill`/`extract_settlement` via `client.messages.parse(model="claude-haiku-4-5", output_format=...)`. Test: mocked `parsed_output` round-trips correctly.

8. **Policy rule extraction** — same file: `PolicyRuleExtraction` (sum insured, room rent limit + type, co-pay %, sub-limits dict), `extract_policy_rules`. Test: mocked parse returns expected structured rules.

9. **Ingestion pipeline** — `app/ingestion/pipeline.py`: `ingest_document(session, document_id, doc_type, pdf_path)` — routes policy docs through chunk+contextualize+embed+extract-rules, bill/settlement through chunk+embed+extract-line-items; sets `Document.status`. Test: mocked sub-components, verify correct rows land in each table per doc type.

10. **Document CRUD API** — `app/api/documents.py`: `POST /documents` (upload, rejects duplicate active type with 409, triggers ingestion), `GET /documents`, `DELETE /documents/{id}` (cascades). Test: upload/list/delete/duplicate-reject via `TestClient`.

11. **Hybrid search** — `app/retrieval/hybrid_search.py`: `hybrid_search(session, query_text, query_embedding, top_k) -> list[SearchResult]`, dense (pgvector cosine) + full-text (`tsvector`), fused via Reciprocal Rank Fusion. Test: seeded chunks, matching query ranks correct chunk first.

12. **Reconciliation rules** — `app/reconciliation/rules.py`: pure functions `apply_sub_limits`, `compute_room_rent_proportionate_deduction`, `compute_admissible_amount`. Test: assert exact figures from the Reference table above.

13. **Reconciliation engine** — `app/reconciliation/engine.py`: `reconcile_claim(session) -> ReconciliationReport | None`, pulls active bill/policy/settlement from DB, applies rules, diffs against the settlement letter's actual approved amount. Test: seeded planted-discrepancy scenario matches the Reference table exactly; missing documents returns `None`.

14. **Agent tools** — `app/agent/tools.py`: `make_search_docs_tool(session)` / `make_reconcile_claim_tool(session)`, `@beta_tool`-decorated, returning JSON (chunk_id/doc_type/page/text; or the reconciliation report). Test: each tool's JSON output shape, and the "missing documents" error path.

15. **Agent chat loop** — `app/agent/chat.py`: `stream_agent_response(session, history, user_message)` via `client.beta.messages.tool_runner(..., stream=True)`, system prompt requiring standalone `search_docs` queries and `[[chunk_id]]` citation markers. Test: mocked tool runner, streamed tokens concatenate correctly.

16. **Chat API & persistence** — `app/api/chat.py`: `POST /chat/message` (SSE: token events + final `done` event with citations resolved/renumbered from `[[chunk_id]]`), `GET /chat/history`. Persists both turns to `messages`. Test: citation resolution + persistence via `TestClient` streaming.

17. **Frontend scaffolding** — Vite+React+TS app, `src/types.ts`, `src/api/client.ts` (`listDocuments`, `uploadDocument`, `deleteDocument`, `getChatHistory`, `streamChatMessage`), base `App.tsx` layout. Test: renders sidebar + chat regions.

18. **Document sidebar** — `components/DocumentSidebar.tsx`: per-type upload inputs, list with delete buttons, wired to the API client. Test: RTL, upload/list/delete flow with mocked API.

19. **Chat panel** — `components/ChatPanel.tsx`: message list, input, consumes SSE stream token-by-token, renders numbered citations. Test: RTL, streamed response renders progressively with citation list.

20. **Synthetic sample data** — `scripts/generate_sample_data.py`: `generate_sample_documents(output_dir)` produces bill/policy/settlement PDFs (reportlab) encoding the exact Reference-table numbers, including the planted ₹70,000 wrong approval. Test: generated PDFs parse back to the expected figures.

21. **End-to-end verification** — integration test (real API keys, skipped otherwise): ingest the generated sample documents through the real pipeline, run `reconcile_claim`, assert it catches the planted ₹5,937.50 discrepancy exactly.

22. **(Optional/stretch) Golden eval script** — `scripts/run_eval.py`: a handful of Q&A pairs run against the ingested sample claim, pass/fail on expected fragments. Manual demo tool, not part of the automated suite — build only if time allows.

## Self-Review Notes

Every spec section maps to a task (ingestion → 3-9, retrieval → 11, reconciliation → 12-13, agent/citations → 14-16, UI → 17-19, sample data/proof → 20-21, eval → 22 optional). Category names (`room_rent`, `ot_charges`, `doctor_fees`, `nursing`, `medicines`, `consumables`, `diagnostics`, `misc`) must stay identical across Tasks 7, 9, and 12 — that's the one place a naming drift would silently break reconciliation.
