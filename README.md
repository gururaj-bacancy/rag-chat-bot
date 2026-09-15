# Policy Compare

A RAG chatbot that helps you understand and verify an Indian health insurance (mediclaim) claim settlement. Upload your hospital bill, your mediclaim policy, and the insurer/TPA's claim settlement letter, then ask why a deduction happened — the bot answers using hybrid document retrieval **and** a deterministic reconciliation engine that recomputes what the settlement should be (including the room-rent-proportionate-deduction math) and flags mismatches against what was actually approved.

## Status

Design and implementation plan are complete; implementation has not started yet.

- [docs/design.md](docs/design.md) — architecture, data flow, reconciliation engine design, trust/honesty rules
- [docs/plan.md](docs/plan.md) — task-by-task implementation roadmap

## Tech Stack

- **Backend:** Python, FastAPI, SQLAlchemy + psycopg3
- **Database:** Postgres + pgvector (hybrid dense/full-text search), via Docker Compose
- **Embeddings:** Voyage AI (`voyage-4-large`)
- **LLM:** Claude Opus 5 (agent, tool use) + Claude Haiku 4.5 (structured extraction)
- **Frontend:** React + Vite + TypeScript

## Why It's Not Just Chat-With-a-PDF

Room rent caps, co-payment, and sub-limits mean a settlement's correctness is a *computation* over the bill and policy, not something retrieval alone can verify. The reconciliation engine extracts structured figures from all three documents and recomputes the expected settlement deterministically — the agent decides per-question whether it needs document retrieval, the reconciliation tool, or both.
