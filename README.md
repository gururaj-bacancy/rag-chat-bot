# Policy Compare

A RAG chatbot that helps you understand and verify an Indian health insurance (mediclaim) claim settlement. Upload your hospital bill, your mediclaim policy, and the insurer/TPA's claim settlement letter, then ask why a deduction happened — the bot answers using hybrid document retrieval **and** a deterministic reconciliation engine that recomputes what the settlement should be (including the room-rent-proportionate-deduction math) and flags mismatches against what was actually approved.

![Policy Compare running locally — the reconciliation engine catching a real ₹5,937.50 discrepancy](docs/screenshot.png)

## Status

Implementation complete — all 22 planned tasks are done. **58 backend tests passing** (1 skipped: the end-to-end test, which needs real API keys) and **13 frontend tests passing**.

- [docs/design.md](docs/design.md) — architecture, data flow, reconciliation engine design, trust/honesty rules
- [docs/plan.md](docs/plan.md) — task-by-task implementation roadmap
- [docs/known-limitations.md](docs/known-limitations.md) — gaps found in review and deliberately deferred (domain-fidelity edge cases, frontend robustness, prompt-injection hardening)

## Tech Stack

- **Backend:** Python, FastAPI, SQLAlchemy + psycopg3
- **Database:** Postgres + pgvector (hybrid dense/full-text search), via Docker Compose
- **Embeddings:** Voyage AI (`voyage-4-large`)
- **LLM:** Claude Opus 5 (agent, tool use) + Claude Haiku 4.5 (structured extraction)
- **Frontend:** React + Vite + TypeScript

## Setup

### 1. Database

```bash
docker compose up -d db
```

That creates the `ragchat` database. The test suite uses a **separate** `ragchat_test` database, which Compose does not create — create it once:

```bash
docker compose exec db psql -U ragchat -d ragchat -c 'CREATE DATABASE ragchat_test;'
```

### 2. Backend environment

> **Python must be 3.12 or older.** `voyageai==0.3.2` (see `backend/requirements.txt`) declares `Requires-Python: >=3.9,<3.13`, so `pip install` fails outright on 3.13+. This project was developed on 3.11.

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. API keys — `.env` goes in `backend/`, not the repo root

> **This is a real footgun.** `app/config.py` declares `env_file=".env"`, which pydantic-settings resolves **relative to the process's working directory**, not to the source file. Every backend command below is run from `backend/`, so the file must be `backend/.env`. A `.env` at the repo root is silently ignored: no error, just empty API keys and confusing auth failures at the first Anthropic/Voyage call.

```bash
cp ../.env.example .env    # from inside backend/
```

Then fill in `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY`. The two `*_DATABASE_URL` values already match the Compose setup and can be left alone.

### 4. Migrations

```bash
# from backend/, with the venv active
python scripts/run_migrations.py                # -> the ragchat database
python scripts/run_migrations.py "postgresql+psycopg://ragchat:ragchat@localhost:5432/ragchat_test"
```

Migrations are idempotent (`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`), so re-running them is safe. The test suite also applies them to `ragchat_test` automatically on every run.

### 5. Run it

```bash
# backend — from backend/, venv active
uvicorn app.main:app --reload            # http://localhost:8000

# frontend — in a second terminal
cd frontend
npm install
npm run dev                              # http://localhost:5173
```

The Vite dev server proxies `/documents` and `/chat` to `http://localhost:8000`, so open the UI at **http://localhost:5173** (not the backend port).

## Try the demo

Generate the synthetic sample claim — three realistic Indian-format PDFs with a planted discrepancy:

```bash
# from backend/, venv active
python scripts/generate_sample_data.py sample_data/generated
```

This writes:

| File | What it contains |
|---|---|
| `sample_bill.pdf` | Apollo City Hospital final bill — 5-day stay at ₹8,000/day room rent, plus OT, doctor, nursing, medicines, consumables and diagnostics charges, ₹1,20,000 total |
| `sample_policy.pdf` | Suraksha Gold policy — ₹5,00,000 sum insured, ₹5,000/day room rent limit, proportionate-deduction clause, 10% co-pay, no sub-limits |
| `sample_settlement.pdf` | MediAssist TPA settlement letter approving **₹70,000** — deliberately wrong |

Upload all three through the sidebar (one per type), then ask the chat *"Is my settlement amount correct according to my policy?"*.

The room rent charged (₹8,000/day) exceeds the ₹5,000/day limit, so the proportionate-deduction ratio is 0.625, which takes ₹35,625 off the ₹95,000 of proportionate charges; after the 10% co-pay the correct approval is **₹75,937.50**. The letter says ₹70,000, so the reconciliation engine reports a **₹5,937.50 discrepancy** — and shows every input it used, so you can check the arithmetic yourself.

## Tests

```bash
cd backend && source venv/bin/activate && python -m pytest    # 58 passed, 1 skipped
cd frontend && npm test                                       # 13 passed
```

The skipped backend test (`tests/test_end_to_end.py`) runs the real ingestion pipeline against real Anthropic and Voyage APIs; it un-skips automatically once `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` are set in the environment. `backend/scripts/run_eval.py` runs a small golden set of questions against an already-ingested sample claim and likewise needs real keys.

## Why It's Not Just Chat-With-a-PDF

Room rent caps, co-payment, and sub-limits mean a settlement's correctness is a *computation* over the bill and policy, not something retrieval alone can verify. The reconciliation engine extracts structured figures from all three documents and recomputes the expected settlement deterministically — the agent decides per-question whether it needs document retrieval, the reconciliation tool, or both.
