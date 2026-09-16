# Known Limitations

Findings surfaced during implementation and the final whole-branch review, deliberately deferred rather than fixed. None block the core demo (upload → ingest → chat → reconcile with the sample claim); all are worth picking up before a real deployment.

## Reconciliation domain gaps

- **`sum_insured` is surfaced but never enforced as a cap.** The reconciliation tool reports it as an input, but nothing clamps the computed approved amount to it.
- **`room_rent_limit_type == "percentage_of_sum_insured"` is unhandled.** Only `"fixed_amount"` triggers the proportionate-deduction calculation — a policy expressing its room rent cap as a percentage of sum insured (common in Indian mediclaim) silently gets zero deduction.
- **Sub-limits are keyed by bill category** (`room_rent`, `ot_charges`, ...), but real policy extraction is more likely to produce procedure-keyed limits (e.g. `"cataract"`). The two won't match without a category↔procedure mapping layer.
- **No non-payable/excluded-items handling.** IRDAI List-I non-payable items (typically extracted into the `misc` category) are treated as fully admissible.

## Trust / correctness

- **Citation marker format can drift across conversation turns.** Persisted history uses the resolved `[1]`, `[2]` footnote form, but the agent is instructed to emit raw `[[chunk_id]]` markers — it may imitate its own prior `[n]` style instead, producing an unlinked citation number.
- **No sanity check that extracted bill line items sum to the bill's stated total**, or that a settlement's line items sum to its stated totals. A single mis-extracted line item currently has no cross-check.
- **No prompt-injection hardening.** Extracted document text flows into both extraction prompts and agent tool results without delimiting or "treat as data, not instructions" framing. The settlement letter — authored by the party whose math is being disputed — is a plausible injection vector.

## Frontend robustness

- **`client.ts`'s SSE decoder has no dedicated test.** All frontend tests mock the API client module wholesale; the chunk-buffering/frame-splitting logic that parses the backend's wire format is untested on the consuming side.
- **`handleResponse`'s error-message fallback can render blank or `[object Object]`** — `res.statusText` can be empty (HTTP/2), and a FastAPI 422 `detail` is an array, not a string.
- **`uploadDocument` doesn't use the shared `handleResponse` helper** added for the other four API functions — it has its own error handling and throws a raw `SyntaxError` on a non-JSON error body.
- **No upload progress feedback, and no client-side file size/type validation** beyond the `accept="application/pdf"` hint, which is not enforced.

## Operational

- **Upload blocks synchronously for the full ingestion** (parsing, one Haiku call per chunk, embeddings, extraction) inside a single request — a real multi-page policy means a multi-minute request with no progress indication and a real risk of a proxy/browser timeout.
- **No `max_iterations` ceiling on the agent's tool-calling loop.**
- **No prompt caching** on the stable system-prompt + tool-definitions prefix, despite `docs/design.md` calling for it — the cheapest available cost lever, not yet built.
- **The reconciliation engine's `return None` branch for "documents present but no extracted data" has no dedicated test** (only "documents missing entirely" is covered).
- **A single migration file with no version tracking.** Fine while every migration is `IF NOT EXISTS`/`ADD COLUMN IF NOT EXISTS`-idempotent; the first genuinely destructive schema change will need a real migration tool.
- **No retry/backoff around Voyage API calls.** Confirmed live: a Voyage account with no payment method on file is capped at 3 requests/minute (the 200M free tokens still apply, only the rate is throttled). Uploading three documents back to back consumes that minute's budget, so an immediately-following chat question's `search_docs` call fails with a `RateLimitError` — the agent handles this gracefully today (falls back to `reconcile_claim` alone and says plainly that it couldn't retrieve document text), but there's no automatic retry, so the degraded, uncited answer is what the user sees until the window resets a bit later.

## Why these were deferred, not fixed

Each was weighed against the reference demo scenario (5-day stay, fixed-amount room rent limit, no sub-limits, a settlement letter with only summary totals) and judged non-blocking for that scenario specifically, even though several matter for a general real-world policy. The working ledger that tracked this reasoning task-by-task was scratch space (git-ignored, not committed) and no longer exists; this file is the durable summary of what it found.
