# Mediclaim Claim Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone RAG chatbot that ingests a hospital bill, a mediclaim policy, and a claim settlement letter, then answers questions about claim deductions — backed by both hybrid document retrieval and a deterministic reconciliation engine that recomputes what the settlement should be and flags mismatches.

**Architecture:** FastAPI backend orchestrates ingestion (PDF parse → chunk/extract → embed → store in Postgres+pgvector), a Claude Opus 5 agent with two tools (`search_docs` hybrid retrieval, `reconcile_claim` deterministic calculator), and a React chat frontend with document upload/delete. Chat history persists in Postgres and reloads across sessions.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 + psycopg3, Postgres 16 + pgvector, Voyage AI (`voyage-4-large`) embeddings, Claude Opus 5 (agent) + Claude Haiku 4.5 (extraction), PyMuPDF, React + Vite + TypeScript, Docker Compose.

**Spec:** [docs/superpowers/specs/2026-09-16-mediclaim-claim-clarity-design.md](../specs/2026-09-16-mediclaim-claim-clarity-design.md)

## Global Constraints

- PDF is the only supported upload format for this plan (no OCR/scanned-image support).
- At most one active document per type (`bill`, `policy`, `settlement`) at a time — uploading a duplicate type is rejected until the existing one is deleted.
- No auth/multi-tenancy — single global workspace, single running conversation.
- Deleting a document must remove it from all future retrieval and reconciliation; past chat messages are never rewritten.
- All money values are `NUMERIC`/`float` in INR; round to 2 decimal places for any user-facing figure.
- Citations are implemented via our own chunk metadata (page number, document, chunk id) captured at ingestion — not Claude's native `citations` content-block feature, which is designed for whole documents passed directly in a request rather than agentically-retrieved tool results.
- Backend routes are sync `def` (not `async def`) — every client used (SQLAlchemy sync engine, Anthropic SDK, Voyage SDK, PyMuPDF) is sync, and FastAPI runs sync handlers in a threadpool automatically.

## Implementation Notes (decisions made while planning, not in the spec verbatim)

- **Policy documents get a second, structured extraction pass** in addition to narrative chunking. The spec's `reconcile_claim` tool needs numeric policy rules (room rent limit, co-pay %, sub-limits) as data, not prose — this was implied by the spec's reconciliation section but not explicit in the ingestion section, so Task 8 adds it explicitly.
- **No separate query-rewriting LLM call.** The agent already sees full chat history on every turn (it's an agentic tool-use loop, not single-shot retrieval), so it can formulate a self-contained `search_docs` query directly from context. A bolted-on rewrite step would be redundant — the system prompt in Task 15 instructs the agent to always pass standalone, context-complete queries to `search_docs`.
- **Citations are numbered footnotes resolved server-side.** The agent is instructed to mark a claim's source inline as `[[chunk_id]]`. The chat API (Task 16) resolves each `chunk_id` to `{document, page_number, doc_type}` via a DB lookup, renumbers them in order of first appearance as `[1]`, `[2]`, ..., and returns a `citations` array alongside the cleaned message text — the frontend never has to parse anything.

---

### Task 1: Project Scaffolding, Docker Compose, FastAPI Skeleton

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `backend/requirements.txt`
- Create: `backend/pytest.ini`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/main.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Produces: `app.config.settings` (a `Settings` instance with `.database_url`, `.anthropic_api_key`, `.voyage_api_key`) — every later backend task imports this.
- Produces: `app.main.app` — the FastAPI instance later tasks mount routers onto.

- [ ] **Step 1: Create Docker Compose for Postgres+pgvector**

```yaml
# docker-compose.yml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: ragchat
      POSTGRES_PASSWORD: ragchat
      POSTGRES_DB: ragchat
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ragchat"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  pgdata:
```

- [ ] **Step 2: Create `.env.example` and `.gitignore`**

```bash
# .env.example
DATABASE_URL=postgresql+psycopg://ragchat:ragchat@localhost:5432/ragchat
TEST_DATABASE_URL=postgresql+psycopg://ragchat:ragchat@localhost:5432/ragchat_test
ANTHROPIC_API_KEY=sk-ant-...
VOYAGE_API_KEY=pa-...
```

```
# .gitignore
.env
venv/
__pycache__/
*.pyc
node_modules/
frontend/dist/
sample_data/generated/
.pytest_cache/
```

- [ ] **Step 3: Create `backend/requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.32.0
sqlalchemy==2.0.36
psycopg[binary]==3.2.3
pgvector==0.3.6
anthropic>=0.60.0
voyageai==0.3.2
pymupdf==1.24.13
reportlab==4.2.5
pydantic==2.9.2
pydantic-settings==2.6.1
python-dotenv==1.0.1
python-multipart==0.0.12
pytest==8.3.3
pytest-mock==3.14.0
httpx==0.27.2
```

- [ ] **Step 4: Write the failing test for the health endpoint**

```python
# backend/tests/test_health.py
from fastapi.testclient import TestClient
from app.main import app

def test_health_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'` or import error, since `app/main.py` doesn't exist yet.

- [ ] **Step 6: Write `app/config.py` and `app/main.py`**

```python
# backend/app/__init__.py
```

```python
# backend/app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://ragchat:ragchat@localhost:5432/ragchat"
    test_database_url: str = "postgresql+psycopg://ragchat:ragchat@localhost:5432/ragchat_test"
    anthropic_api_key: str = ""
    voyage_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
```

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Mediclaim Claim Clarity")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 8: Create `backend/pytest.ini`**

```ini
[pytest]
testpaths = tests
pythonpath = .
```

- [ ] **Step 9: Bring up Postgres and verify it's reachable**

Run: `docker compose up -d db && sleep 3 && docker compose exec db pg_isready -U ragchat`
Expected: `accepting connections`

- [ ] **Step 10: Commit**

```bash
git add docker-compose.yml .env.example .gitignore backend/
git commit -m "chore: scaffold FastAPI backend and Postgres+pgvector compose"
```

---

### Task 2: Database Schema and Connection

**Files:**
- Create: `backend/migrations/001_init.sql`
- Create: `backend/scripts/run_migrations.py`
- Create: `backend/app/db/__init__.py`
- Create: `backend/app/db/session.py`
- Create: `backend/app/db/models.py`
- Test: `backend/tests/conftest.py`
- Test: `backend/tests/test_db.py`

**Interfaces:**
- Consumes: `app.config.settings` (Task 1).
- Produces: `app.db.session.get_engine() -> Engine`, `app.db.session.SessionLocal` (sessionmaker) — every task touching the DB uses these.
- Produces: `app.db.models.Document`, `Chunk`, `LineItem`, `PolicyRule`, `Message` (SQLAlchemy ORM classes) — every later task's DB interactions use these exact class/column names.

- [ ] **Step 1: Write the SQL migration**

```sql
-- backend/migrations/001_init.sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    doc_type VARCHAR(20) NOT NULL CHECK (doc_type IN ('bill', 'policy', 'settlement')),
    filename VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processing' CHECK (status IN ('processing', 'indexed', 'failed')),
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    contextual_text TEXT NOT NULL,
    page_number INTEGER,
    embedding vector(1024),
    search_vector TSVECTOR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_search_vector_idx ON chunks USING GIN (search_vector);

CREATE TABLE IF NOT EXISTS line_items (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    category VARCHAR(30) NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    claimed_amount NUMERIC(12,2),
    approved_amount NUMERIC(12,2),
    deducted_amount NUMERIC(12,2),
    deduction_reason TEXT
);

CREATE TABLE IF NOT EXISTS policy_rules (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    sum_insured NUMERIC(12,2) NOT NULL,
    room_rent_limit_per_day NUMERIC(12,2),
    room_rent_limit_type VARCHAR(30) NOT NULL,
    co_pay_percentage NUMERIC(5,2) NOT NULL DEFAULT 0,
    sub_limits JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    role VARCHAR(10) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    citations JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- [ ] **Step 2: Write the migration runner**

```python
# backend/scripts/run_migrations.py
import sys
from pathlib import Path
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings

def run_migrations(database_url: str) -> None:
    engine = create_engine(database_url)
    migrations_dir = Path(__file__).resolve().parents[1] / "migrations"
    with engine.begin() as conn:
        for path in sorted(migrations_dir.glob("*.sql")):
            conn.execute(text(path.read_text()))
    engine.dispose()

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else settings.database_url
    run_migrations(target)
    print(f"Migrations applied to {target}")
```

- [ ] **Step 3: Write `app/db/session.py` and `app/db/models.py`**

```python
# backend/app/db/__init__.py
```

```python
# backend/app/db/session.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings

_engine = None
SessionLocal = None

def get_engine(database_url: str | None = None):
    global _engine, SessionLocal
    if _engine is None or database_url is not None:
        _engine = create_engine(database_url or settings.database_url)
        SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine
```

```python
# backend/app/db/models.py
from datetime import datetime
from sqlalchemy import String, Integer, Text, ForeignKey, Numeric, JSON, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

class Base(DeclarativeBase):
    pass

class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_type: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="processing")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_text: Mapped[str] = mapped_column(Text)
    contextual_text: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)

class LineItem(Base):
    __tablename__ = "line_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30))
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    claimed_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    approved_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    deducted_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    deduction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

class PolicyRule(Base):
    __tablename__ = "policy_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    sum_insured: Mapped[float] = mapped_column(Numeric(12, 2))
    room_rent_limit_per_day: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    room_rent_limit_type: Mapped[str] = mapped_column(String(30))
    co_pay_percentage: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    sub_limits: Mapped[dict] = mapped_column(JSON, default=dict)

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: Write `tests/conftest.py` — test DB fixture**

```python
# backend/tests/conftest.py
import pytest
from sqlalchemy import text
from app.config import settings
from app.db.session import get_engine
from app.db.models import Base

@pytest.fixture(scope="session", autouse=True)
def _setup_test_db():
    engine = get_engine(settings.test_database_url)
    from scripts.run_migrations import run_migrations
    run_migrations(settings.test_database_url)
    yield engine

@pytest.fixture()
def db_session(_setup_test_db):
    engine = get_engine(settings.test_database_url)
    from app.db.session import SessionLocal
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"TRUNCATE TABLE {table.name} RESTART IDENTITY CASCADE"))
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

- [ ] **Step 5: Write the failing test**

```python
# backend/tests/test_db.py
from app.db.models import Document

def test_insert_and_query_document(db_session):
    doc = Document(doc_type="bill", filename="bill.pdf", status="processing")
    db_session.add(doc)
    db_session.commit()

    fetched = db_session.query(Document).filter_by(filename="bill.pdf").one()
    assert fetched.doc_type == "bill"
    assert fetched.status == "processing"
```

- [ ] **Step 6: Create the test database and run the test to verify it fails**

Run:
```bash
docker compose exec db psql -U ragchat -c "CREATE DATABASE ragchat_test;"
cd backend && python -m pytest tests/test_db.py -v
```
Expected: FAIL initially with `relation "documents" does not exist` before migrations run automatically via the fixture on first pass — if it still fails after that, check `run_migrations` output for SQL errors.

- [ ] **Step 7: Run again to verify it passes**

Run: `cd backend && python -m pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/migrations backend/scripts backend/app/db backend/tests
git commit -m "feat: add database schema, models, and test DB fixture"
```

---

### Task 3: PDF Parsing Module

**Files:**
- Create: `backend/app/ingestion/__init__.py`
- Create: `backend/app/ingestion/pdf_parser.py`
- Test: `backend/tests/test_pdf_parser.py`

**Interfaces:**
- Produces: `parse_pdf(path: str) -> list[TextBlock]` where `TextBlock` has `.text: str`, `.page_number: int` (1-indexed) — Tasks 4, 7, 8, 9 consume this.

- [ ] **Step 1: Write the failing test using an in-memory generated PDF**

```python
# backend/tests/test_pdf_parser.py
import fitz
from app.ingestion.pdf_parser import parse_pdf

def _make_test_pdf(path, pages_text: list[str]):
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()

def test_parse_pdf_extracts_text_with_page_numbers(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    _make_test_pdf(str(pdf_path), ["Page one content", "Page two content"])

    blocks = parse_pdf(str(pdf_path))

    assert any("Page one content" in b.text and b.page_number == 1 for b in blocks)
    assert any("Page two content" in b.text and b.page_number == 2 for b in blocks)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pdf_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingestion.pdf_parser'`

- [ ] **Step 3: Implement**

```python
# backend/app/ingestion/__init__.py
```

```python
# backend/app/ingestion/pdf_parser.py
from dataclasses import dataclass
import fitz

@dataclass
class TextBlock:
    text: str
    page_number: int

def parse_pdf(path: str) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    doc = fitz.open(path)
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            for raw in page.get_text("blocks"):
                text = raw[4].strip()
                if text:
                    blocks.append(TextBlock(text=text, page_number=page_index + 1))
    finally:
        doc.close()
    return blocks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_pdf_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/pdf_parser.py backend/app/ingestion/__init__.py backend/tests/test_pdf_parser.py
git commit -m "feat: add layout-aware PDF parsing with page numbers"
```

---

### Task 4: Policy Chunker

**Files:**
- Create: `backend/app/ingestion/chunker.py`
- Test: `backend/tests/test_chunker.py`

**Interfaces:**
- Consumes: `app.ingestion.pdf_parser.TextBlock` (Task 3).
- Produces: `chunk_policy_blocks(blocks: list[TextBlock]) -> list[Chunk]` where `Chunk` has `.text: str`, `.page_number: int` — Task 6 and Task 9 consume this.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chunker.py
from app.ingestion.pdf_parser import TextBlock
from app.ingestion.chunker import chunk_policy_blocks

def test_chunk_splits_on_heading_like_lines():
    blocks = [
        TextBlock(text="ROOM RENT AND ICU CHARGES", page_number=1),
        TextBlock(text="The company will pay up to Rs. 5,000 per day.", page_number=1),
        TextBlock(text="CO-PAYMENT", page_number=1),
        TextBlock(text="A co-payment of 10% applies to all claims.", page_number=2),
    ]

    chunks = chunk_policy_blocks(blocks)

    assert len(chunks) == 2
    assert "ROOM RENT" in chunks[0].text
    assert "Rs. 5,000" in chunks[0].text
    assert chunks[0].page_number == 1
    assert "CO-PAYMENT" in chunks[1].text
    assert chunks[1].page_number == 2

def test_heading_heuristic_is_short_all_caps_line():
    from app.ingestion.chunker import _looks_like_heading
    assert _looks_like_heading("ROOM RENT AND ICU CHARGES") is True
    assert _looks_like_heading("The company will pay up to Rs. 5,000 per day.") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_chunker.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/app/ingestion/chunker.py
from dataclasses import dataclass
from app.ingestion.pdf_parser import TextBlock

@dataclass
class Chunk:
    text: str
    page_number: int

def _looks_like_heading(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    is_mostly_upper = sum(1 for c in letters if c.isupper()) / len(letters) > 0.9
    return is_mostly_upper and len(text) <= 60

def chunk_policy_blocks(blocks: list[TextBlock]) -> list[Chunk]:
    chunks: list[Chunk] = []
    current_lines: list[str] = []
    current_page: int | None = None

    def flush():
        if current_lines:
            chunks.append(Chunk(text="\n".join(current_lines), page_number=current_page or 1))

    for block in blocks:
        if _looks_like_heading(block.text) and current_lines:
            flush()
            current_lines = [block.text]
            current_page = block.page_number
        else:
            if current_page is None:
                current_page = block.page_number
            current_lines.append(block.text)
    flush()
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_chunker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/chunker.py backend/tests/test_chunker.py
git commit -m "feat: add heading-based chunker for policy documents"
```

---

### Task 5: Voyage Embeddings Client

**Files:**
- Create: `backend/app/ingestion/embeddings.py`
- Test: `backend/tests/test_embeddings.py`

**Interfaces:**
- Produces: `embed_documents(texts: list[str]) -> list[list[float]]`, `embed_query(text: str) -> list[float]` — Tasks 9 and 11 consume these.

- [ ] **Step 1: Write the failing test with a mocked Voyage client**

```python
# backend/tests/test_embeddings.py
from unittest.mock import patch, MagicMock
from app.ingestion.embeddings import embed_documents, embed_query

@patch("app.ingestion.embeddings._client")
def test_embed_documents_calls_voyage_with_document_input_type(mock_client):
    mock_client.embed.return_value = MagicMock(embeddings=[[0.1] * 1024, [0.2] * 1024])

    result = embed_documents(["chunk one", "chunk two"])

    mock_client.embed.assert_called_once_with(
        ["chunk one", "chunk two"], model="voyage-4-large", input_type="document"
    )
    assert result == [[0.1] * 1024, [0.2] * 1024]

@patch("app.ingestion.embeddings._client")
def test_embed_query_calls_voyage_with_query_input_type(mock_client):
    mock_client.embed.return_value = MagicMock(embeddings=[[0.3] * 1024])

    result = embed_query("what is my room rent limit?")

    mock_client.embed.assert_called_once_with(
        ["what is my room rent limit?"], model="voyage-4-large", input_type="query"
    )
    assert result == [0.3] * 1024
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_embeddings.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/app/ingestion/embeddings.py
import voyageai
from app.config import settings

_client = voyageai.Client(api_key=settings.voyage_api_key)

EMBEDDING_MODEL = "voyage-4-large"

def embed_documents(texts: list[str]) -> list[list[float]]:
    result = _client.embed(texts, model=EMBEDDING_MODEL, input_type="document")
    return result.embeddings

def embed_query(text: str) -> list[float]:
    result = _client.embed([text], model=EMBEDDING_MODEL, input_type="query")
    return result.embeddings[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_embeddings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/embeddings.py backend/tests/test_embeddings.py
git commit -m "feat: add Voyage AI embeddings client"
```

---

### Task 6: Contextual Blurb Generator

**Files:**
- Create: `backend/app/ingestion/contextual.py`
- Test: `backend/tests/test_contextual.py`

**Interfaces:**
- Produces: `generate_contextual_text(chunk_text: str, document_summary: str) -> str` (returns `blurb + "\n\n" + chunk_text`) — Task 9 consumes this.

- [ ] **Step 1: Write the failing test with a mocked Anthropic client**

```python
# backend/tests/test_contextual.py
from unittest.mock import patch, MagicMock
from app.ingestion.contextual import generate_contextual_text

@patch("app.ingestion.contextual._client")
def test_generate_contextual_text_prepends_blurb(mock_client):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="This clause covers room rent limits under the Gold plan.")]
    mock_client.messages.create.return_value = mock_response

    result = generate_contextual_text(
        chunk_text="The company will pay up to Rs. 5,000 per day for room rent.",
        document_summary="Gold Mediclaim Policy for individual sum insured Rs. 5,00,000.",
    )

    assert result.startswith("This clause covers room rent limits under the Gold plan.")
    assert "The company will pay up to Rs. 5,000 per day for room rent." in result
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-haiku-4-5"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_contextual.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/app/ingestion/contextual.py
import anthropic
from app.config import settings

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

CONTEXTUAL_PROMPT = """Here is a document summary:
<document_summary>
{document_summary}
</document_summary>

Here is a chunk from that document:
<chunk>
{chunk_text}
</chunk>

Write a short (1-2 sentence) blurb that situates this chunk within the \
overall document, so it can be understood on its own. Answer with only \
the blurb, no preamble."""

def generate_contextual_text(chunk_text: str, document_summary: str) -> str:
    response = _client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": CONTEXTUAL_PROMPT.format(
                document_summary=document_summary, chunk_text=chunk_text
            ),
        }],
    )
    blurb = next(b.text for b in response.content if b.type == "text").strip()
    return f"{blurb}\n\n{chunk_text}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_contextual.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/contextual.py backend/tests/test_contextual.py
git commit -m "feat: add contextual retrieval blurb generation via Haiku"
```

---

### Task 7: Bill and Settlement Structured Extraction

**Files:**
- Create: `backend/app/ingestion/extraction.py`
- Test: `backend/tests/test_extraction.py`

**Interfaces:**
- Produces: `LineItemExtraction` (Pydantic: `description: str`, `category: Literal[...]`, `amount: float`), `BillExtraction` (Pydantic: `line_items: list[LineItemExtraction]`, `room_category: str | None`, `room_rent_per_day: float | None`), `SettlementLineItemExtraction` (Pydantic: `description`, `claimed_amount`, `approved_amount`, `deducted_amount`, `deduction_reason: str | None`), `SettlementExtraction` (Pydantic: `line_items: list[SettlementLineItemExtraction]`, `total_claimed`, `total_approved`, `total_deducted`).
- Produces: `extract_bill(text: str) -> BillExtraction`, `extract_settlement(text: str) -> SettlementExtraction` — Task 9 consumes these.

- [ ] **Step 1: Write the failing test with a mocked `messages.parse`**

```python
# backend/tests/test_extraction.py
from unittest.mock import patch, MagicMock
from app.ingestion.extraction import (
    extract_bill, extract_settlement, BillExtraction, LineItemExtraction,
    SettlementExtraction, SettlementLineItemExtraction,
)

@patch("app.ingestion.extraction._client")
def test_extract_bill_parses_line_items(mock_client):
    expected = BillExtraction(
        line_items=[
            LineItemExtraction(description="Room rent (5 days)", category="room_rent", amount=40000.0),
            LineItemExtraction(description="OT charges", category="ot_charges", amount=30000.0),
        ],
        room_category="Private Room",
        room_rent_per_day=8000.0,
    )
    mock_client.messages.parse.return_value = MagicMock(parsed_output=expected)

    result = extract_bill("HOSPITAL FINAL BILL\nRoom rent (5 days): Rs 40,000\nOT charges: Rs 30,000")

    assert result == expected
    call_kwargs = mock_client.messages.parse.call_args.kwargs
    assert call_kwargs["model"] == "claude-haiku-4-5"
    assert call_kwargs["output_format"] is BillExtraction

@patch("app.ingestion.extraction._client")
def test_extract_settlement_parses_deductions(mock_client):
    expected = SettlementExtraction(
        line_items=[
            SettlementLineItemExtraction(
                description="Room rent proportionate deduction",
                claimed_amount=40000.0, approved_amount=25000.0,
                deducted_amount=15000.0, deduction_reason="Room rent exceeds policy limit",
            ),
        ],
        total_claimed=120000.0, total_approved=70000.0, total_deducted=50000.0,
    )
    mock_client.messages.parse.return_value = MagicMock(parsed_output=expected)

    result = extract_settlement("CLAIM SETTLEMENT LETTER\nTotal claimed: 120000\nTotal approved: 70000")

    assert result == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_extraction.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/app/ingestion/extraction.py
from typing import Literal
import anthropic
from pydantic import BaseModel
from app.config import settings

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

LineItemCategory = Literal[
    "room_rent", "ot_charges", "doctor_fees", "nursing",
    "medicines", "consumables", "diagnostics", "misc",
]

class LineItemExtraction(BaseModel):
    description: str
    category: LineItemCategory
    amount: float

class BillExtraction(BaseModel):
    line_items: list[LineItemExtraction]
    room_category: str | None = None
    room_rent_per_day: float | None = None

class SettlementLineItemExtraction(BaseModel):
    description: str
    claimed_amount: float
    approved_amount: float
    deducted_amount: float
    deduction_reason: str | None = None

class SettlementExtraction(BaseModel):
    line_items: list[SettlementLineItemExtraction]
    total_claimed: float
    total_approved: float
    total_deducted: float

def extract_bill(text: str) -> BillExtraction:
    response = _client.messages.parse(
        model="claude-haiku-4-5",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": (
                "Extract every line item, its category, and amount from this "
                "hospital bill, plus the room category and per-day room rent "
                f"if stated:\n\n{text}"
            ),
        }],
        output_format=BillExtraction,
    )
    return response.parsed_output

def extract_settlement(text: str) -> SettlementExtraction:
    response = _client.messages.parse(
        model="claude-haiku-4-5",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": (
                "Extract every claimed/approved/deducted line item and the "
                f"totals from this insurance claim settlement letter:\n\n{text}"
            ),
        }],
        output_format=SettlementExtraction,
    )
    return response.parsed_output
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_extraction.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/extraction.py backend/tests/test_extraction.py
git commit -m "feat: add structured extraction for bill and settlement line items"
```

---

### Task 8: Policy Rule Extraction

**Files:**
- Modify: `backend/app/ingestion/extraction.py`
- Test: `backend/tests/test_policy_rules_extraction.py`

**Interfaces:**
- Produces: `PolicyRuleExtraction` (Pydantic: `sum_insured: float`, `room_rent_limit_per_day: float | None`, `room_rent_limit_type: Literal["fixed_amount", "percentage_of_sum_insured", "no_limit"]`, `co_pay_percentage: float`, `sub_limits: dict[str, float]`), `extract_policy_rules(text: str) -> PolicyRuleExtraction` — Task 9 and Task 13 consume this.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_policy_rules_extraction.py
from unittest.mock import patch, MagicMock
from app.ingestion.extraction import extract_policy_rules, PolicyRuleExtraction

@patch("app.ingestion.extraction._client")
def test_extract_policy_rules_parses_limits(mock_client):
    expected = PolicyRuleExtraction(
        sum_insured=500000.0,
        room_rent_limit_per_day=5000.0,
        room_rent_limit_type="fixed_amount",
        co_pay_percentage=10.0,
        sub_limits={},
    )
    mock_client.messages.parse.return_value = MagicMock(parsed_output=expected)

    result = extract_policy_rules(
        "Sum insured: Rs 5,00,000. Room rent limit: Rs 5,000/day. Co-payment: 10%."
    )

    assert result == expected
    call_kwargs = mock_client.messages.parse.call_args.kwargs
    assert call_kwargs["output_format"] is PolicyRuleExtraction
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_policy_rules_extraction.py -v`
Expected: FAIL — `ImportError: cannot import name 'extract_policy_rules'`

- [ ] **Step 3: Add to `app/ingestion/extraction.py`**

```python
# Append to backend/app/ingestion/extraction.py

RoomRentLimitType = Literal["fixed_amount", "percentage_of_sum_insured", "no_limit"]

class PolicyRuleExtraction(BaseModel):
    sum_insured: float
    room_rent_limit_per_day: float | None = None
    room_rent_limit_type: RoomRentLimitType
    co_pay_percentage: float = 0.0
    sub_limits: dict[str, float] = {}

def extract_policy_rules(text: str) -> PolicyRuleExtraction:
    response = _client.messages.parse(
        model="claude-haiku-4-5",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": (
                "Extract the sum insured, room rent limit (and whether it is a "
                "fixed amount, a percentage of sum insured, or no limit), the "
                "co-payment percentage, and any per-procedure sub-limits from "
                f"this mediclaim policy document:\n\n{text}"
            ),
        }],
        output_format=PolicyRuleExtraction,
    )
    return response.parsed_output
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_policy_rules_extraction.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/extraction.py backend/tests/test_policy_rules_extraction.py
git commit -m "feat: add structured extraction of policy rules"
```

---

### Task 9: Ingestion Pipeline Orchestration

**Files:**
- Create: `backend/app/ingestion/pipeline.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `parse_pdf` (3), `chunk_policy_blocks` (4), `embed_documents` (5), `generate_contextual_text` (6), `extract_bill`/`extract_settlement`/`extract_policy_rules` (7, 8), ORM models (2).
- Produces: `ingest_document(session, document_id: int, doc_type: str, pdf_path: str) -> None` — writes `Chunk`, `LineItem`, and/or `PolicyRule` rows for the given `document_id`, and sets `Document.status`. Task 10 consumes this.

- [ ] **Step 1: Write the failing test — policy path**

```python
# backend/tests/test_pipeline.py
from unittest.mock import patch
from app.db.models import Document, Chunk, PolicyRule, LineItem
from app.ingestion.pipeline import ingest_document
from app.ingestion.pdf_parser import TextBlock
from app.ingestion.extraction import BillExtraction, LineItemExtraction, PolicyRuleExtraction

def test_ingest_policy_document_creates_chunks_and_policy_rule(db_session, tmp_path):
    doc = Document(doc_type="policy", filename="policy.pdf", status="processing")
    db_session.add(doc)
    db_session.commit()
    fake_pdf = tmp_path / "policy.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("app.ingestion.pipeline.parse_pdf") as mock_parse, \
         patch("app.ingestion.pipeline.generate_contextual_text") as mock_ctx, \
         patch("app.ingestion.pipeline.embed_documents") as mock_embed, \
         patch("app.ingestion.pipeline.extract_policy_rules") as mock_rules:
        mock_parse.return_value = [
            TextBlock(text="ROOM RENT", page_number=1),
            TextBlock(text="Up to Rs 5,000 per day.", page_number=1),
        ]
        mock_ctx.side_effect = lambda chunk_text, document_summary: f"[ctx] {chunk_text}"
        mock_embed.return_value = [[0.1] * 1024]
        mock_rules.return_value = PolicyRuleExtraction(
            sum_insured=500000.0, room_rent_limit_per_day=5000.0,
            room_rent_limit_type="fixed_amount", co_pay_percentage=10.0, sub_limits={},
        )

        ingest_document(db_session, doc.id, "policy", str(fake_pdf))

    db_session.refresh(doc)
    assert doc.status == "indexed"
    chunks = db_session.query(Chunk).filter_by(document_id=doc.id).all()
    assert len(chunks) == 1
    assert chunks[0].embedding is not None
    rule = db_session.query(PolicyRule).filter_by(document_id=doc.id).one()
    assert rule.room_rent_limit_per_day == 5000.0

def test_ingest_bill_document_creates_line_items(db_session, tmp_path):
    doc = Document(doc_type="bill", filename="bill.pdf", status="processing")
    db_session.add(doc)
    db_session.commit()
    fake_pdf = tmp_path / "bill.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("app.ingestion.pipeline.parse_pdf") as mock_parse, \
         patch("app.ingestion.pipeline.generate_contextual_text") as mock_ctx, \
         patch("app.ingestion.pipeline.embed_documents") as mock_embed, \
         patch("app.ingestion.pipeline.extract_bill") as mock_extract:
        mock_parse.return_value = [TextBlock(text="Room rent: 40000", page_number=1)]
        mock_ctx.side_effect = lambda chunk_text, document_summary: f"[ctx] {chunk_text}"
        mock_embed.return_value = [[0.2] * 1024]
        mock_extract.return_value = BillExtraction(
            line_items=[LineItemExtraction(description="Room rent", category="room_rent", amount=40000.0)],
            room_category="Private Room", room_rent_per_day=8000.0,
        )

        ingest_document(db_session, doc.id, "bill", str(fake_pdf))

    db_session.refresh(doc)
    assert doc.status == "indexed"
    items = db_session.query(LineItem).filter_by(document_id=doc.id).all()
    assert len(items) == 1
    assert items[0].category == "room_rent"
    assert float(items[0].amount) == 40000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/app/ingestion/pipeline.py
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session
from app.db.models import Document, Chunk, LineItem, PolicyRule
from app.ingestion.pdf_parser import parse_pdf
from app.ingestion.chunker import chunk_policy_blocks
from app.ingestion.contextual import generate_contextual_text
from app.ingestion.embeddings import embed_documents
from app.ingestion.extraction import extract_bill, extract_settlement, extract_policy_rules

def _full_text(blocks) -> str:
    return "\n".join(b.text for b in blocks)

def _ingest_policy(session: Session, document_id: int, blocks) -> None:
    doc_summary = _full_text(blocks)[:1000]
    chunks = chunk_policy_blocks(blocks)
    contextual_texts = [generate_contextual_text(c.text, doc_summary) for c in chunks]
    embeddings = embed_documents(contextual_texts)

    for chunk, ctx_text, embedding in zip(chunks, contextual_texts, embeddings):
        session.add(Chunk(
            document_id=document_id, chunk_text=chunk.text,
            contextual_text=ctx_text, page_number=chunk.page_number,
            embedding=embedding,
        ))

    rules = extract_policy_rules(doc_summary)
    session.add(PolicyRule(
        document_id=document_id, sum_insured=rules.sum_insured,
        room_rent_limit_per_day=rules.room_rent_limit_per_day,
        room_rent_limit_type=rules.room_rent_limit_type,
        co_pay_percentage=rules.co_pay_percentage,
        sub_limits=rules.sub_limits,
    ))

def _ingest_bill_or_settlement(session: Session, document_id: int, doc_type: str, blocks) -> None:
    full_text = _full_text(blocks)
    doc_summary = full_text[:1000]

    # Index raw text for citation-backed retrieval, same as policy chunks.
    chunks = chunk_policy_blocks(blocks)
    contextual_texts = [generate_contextual_text(c.text, doc_summary) for c in chunks]
    embeddings = embed_documents(contextual_texts)
    for chunk, ctx_text, embedding in zip(chunks, contextual_texts, embeddings):
        session.add(Chunk(
            document_id=document_id, chunk_text=chunk.text,
            contextual_text=ctx_text, page_number=chunk.page_number,
            embedding=embedding,
        ))

    if doc_type == "bill":
        extraction = extract_bill(full_text)
        for item in extraction.line_items:
            session.add(LineItem(
                document_id=document_id, description=item.description,
                category=item.category, amount=item.amount,
            ))
    else:  # settlement
        extraction = extract_settlement(full_text)
        for item in extraction.line_items:
            session.add(LineItem(
                document_id=document_id, description=item.description,
                category="settlement_line", amount=item.claimed_amount,
                claimed_amount=item.claimed_amount, approved_amount=item.approved_amount,
                deducted_amount=item.deducted_amount, deduction_reason=item.deduction_reason,
            ))

def ingest_document(session: Session, document_id: int, doc_type: str, pdf_path: str) -> None:
    document = session.get(Document, document_id)
    try:
        blocks = parse_pdf(pdf_path)
        if doc_type == "policy":
            _ingest_policy(session, document_id, blocks)
        else:
            _ingest_bill_or_settlement(session, document_id, doc_type, blocks)
        document.status = "indexed"
        session.commit()
        session.execute(sql_text(
            "UPDATE chunks SET search_vector = to_tsvector('english', chunk_text) "
            "WHERE document_id = :doc_id"
        ), {"doc_id": document_id})
        session.commit()
    except Exception:
        document.status = "failed"
        session.commit()
        raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: wire ingestion pipeline for policy, bill, and settlement documents"
```

---

### Task 10: Document CRUD API

**Files:**
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/documents.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_documents_api.py`

**Interfaces:**
- Consumes: `ingest_document` (Task 9), `Document` model (Task 2), `SessionLocal` (Task 2).
- Produces: `POST /documents` (multipart: `file`, `doc_type`), `GET /documents`, `DELETE /documents/{id}` — Task 16's chat wiring and the frontend (Tasks 18-19) consume these endpoints.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_documents_api.py
import io
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app
from app.db.models import Document, Chunk

def _fake_pdf_bytes():
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Sum insured Rs 5,00,000. Room rent limit Rs 5,000/day.")
    data = doc.tobytes()
    doc.close()
    return data

def test_upload_document_triggers_ingestion(db_session, monkeypatch):
    monkeypatch.setattr("app.api.documents.SessionLocal", lambda: db_session)
    client = TestClient(app)

    with patch("app.api.documents.ingest_document") as mock_ingest:
        response = client.post(
            "/documents",
            files={"file": ("policy.pdf", io.BytesIO(_fake_pdf_bytes()), "application/pdf")},
            data={"doc_type": "policy"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["doc_type"] == "policy"
    mock_ingest.assert_called_once()
    doc = db_session.query(Document).filter_by(id=body["id"]).one()
    assert doc.filename == "policy.pdf"

def test_upload_rejects_duplicate_active_type(db_session, monkeypatch):
    monkeypatch.setattr("app.api.documents.SessionLocal", lambda: db_session)
    db_session.add(Document(doc_type="policy", filename="existing.pdf", status="indexed"))
    db_session.commit()
    client = TestClient(app)

    response = client.post(
        "/documents",
        files={"file": ("new.pdf", io.BytesIO(_fake_pdf_bytes()), "application/pdf")},
        data={"doc_type": "policy"},
    )

    assert response.status_code == 409

def test_list_documents(db_session, monkeypatch):
    monkeypatch.setattr("app.api.documents.SessionLocal", lambda: db_session)
    db_session.add(Document(doc_type="bill", filename="bill.pdf", status="indexed"))
    db_session.commit()
    client = TestClient(app)

    response = client.get("/documents")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["filename"] == "bill.pdf"

def test_delete_document_cascades_chunks(db_session, monkeypatch):
    monkeypatch.setattr("app.api.documents.SessionLocal", lambda: db_session)
    doc = Document(doc_type="bill", filename="bill.pdf", status="indexed")
    db_session.add(doc)
    db_session.commit()
    db_session.add(Chunk(document_id=doc.id, chunk_text="x", contextual_text="x", page_number=1))
    db_session.commit()
    client = TestClient(app)

    response = client.delete(f"/documents/{doc.id}")

    assert response.status_code == 204
    assert db_session.query(Document).filter_by(id=doc.id).first() is None
    assert db_session.query(Chunk).filter_by(document_id=doc.id).first() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_documents_api.py -v`
Expected: FAIL — `ModuleNotFoundError` / 404 on unregistered routes

- [ ] **Step 3: Implement**

```python
# backend/app/api/__init__.py
```

```python
# backend/app/api/documents.py
import shutil
import tempfile
from pathlib import Path
from fastapi import APIRouter, UploadFile, Form, HTTPException
from app.db.session import SessionLocal, get_engine
from app.db.models import Document
from app.ingestion.pipeline import ingest_document

get_engine()  # ensure SessionLocal is initialized
router = APIRouter(prefix="/documents", tags=["documents"])

VALID_TYPES = {"bill", "policy", "settlement"}

@router.post("", status_code=201)
def upload_document(file: UploadFile, doc_type: str = Form(...)):
    if doc_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"doc_type must be one of {VALID_TYPES}")

    session = SessionLocal()
    try:
        existing = session.query(Document).filter(
            Document.doc_type == doc_type, Document.status != "failed"
        ).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"An active '{doc_type}' document already exists (id={existing.id}); delete it first.",
            )

        document = Document(doc_type=doc_type, filename=file.filename, status="processing")
        session.add(document)
        session.commit()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        try:
            ingest_document(session, document.id, doc_type, tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        session.refresh(document)
        return {"id": document.id, "doc_type": document.doc_type, "filename": document.filename, "status": document.status}
    finally:
        session.close()

@router.get("")
def list_documents():
    session = SessionLocal()
    try:
        docs = session.query(Document).order_by(Document.uploaded_at).all()
        return [
            {"id": d.id, "doc_type": d.doc_type, "filename": d.filename, "status": d.status}
            for d in docs
        ]
    finally:
        session.close()

@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: int):
    session = SessionLocal()
    try:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        session.delete(document)
        session.commit()
    finally:
        session.close()
```

- [ ] **Step 4: Mount the router**

```python
# backend/app/main.py — add these lines
from app.api.documents import router as documents_router

app.include_router(documents_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_documents_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api backend/app/main.py backend/tests/test_documents_api.py
git commit -m "feat: add document upload, list, and delete API"
```

---

### Task 11: Hybrid Search Module

**Files:**
- Create: `backend/app/retrieval/__init__.py`
- Create: `backend/app/retrieval/hybrid_search.py`
- Test: `backend/tests/test_hybrid_search.py`

**Interfaces:**
- Consumes: `Chunk` model (Task 2), a pre-computed query embedding (caller-supplied, so this module has no dependency on `embeddings.py` and stays trivially testable with hand-crafted vectors).
- Produces: `hybrid_search(session, query_text: str, query_embedding: list[float], top_k: int = 8) -> list[SearchResult]` where `SearchResult` has `.chunk_id`, `.document_id`, `.chunk_text`, `.page_number`, `.score` — Task 14 consumes this.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_hybrid_search.py
from app.db.models import Document, Chunk
from app.retrieval.hybrid_search import hybrid_search

def test_hybrid_search_ranks_matching_chunk_first(db_session):
    doc = Document(doc_type="policy", filename="policy.pdf", status="indexed")
    db_session.add(doc)
    db_session.commit()

    close_vector = [1.0] + [0.0] * 1023
    far_vector = [0.0] * 1023 + [1.0]

    db_session.add(Chunk(
        document_id=doc.id, chunk_text="Room rent limit is Rs 5000 per day",
        contextual_text="Room rent limit is Rs 5000 per day", page_number=2,
        embedding=close_vector,
    ))
    db_session.add(Chunk(
        document_id=doc.id, chunk_text="Waiting period is 30 days for new policies",
        contextual_text="Waiting period is 30 days for new policies", page_number=5,
        embedding=far_vector,
    ))
    db_session.commit()
    from sqlalchemy import text
    db_session.execute(text(
        "UPDATE chunks SET search_vector = to_tsvector('english', chunk_text)"
    ))
    db_session.commit()

    results = hybrid_search(db_session, "room rent limit", close_vector, top_k=2)

    assert len(results) == 2
    assert results[0].chunk_text.startswith("Room rent limit")
    assert results[0].page_number == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_hybrid_search.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/app/retrieval/__init__.py
```

```python
# backend/app/retrieval/hybrid_search.py
from dataclasses import dataclass
from sqlalchemy import text
from sqlalchemy.orm import Session

RRF_K = 60

@dataclass
class SearchResult:
    chunk_id: int
    document_id: int
    chunk_text: str
    page_number: int | None
    score: float

def hybrid_search(session: Session, query_text: str, query_embedding: list[float], top_k: int = 8) -> list[SearchResult]:
    fetch_n = max(top_k * 5, 20)
    embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    dense_rows = session.execute(text(
        "SELECT id, document_id, chunk_text, page_number "
        "FROM chunks ORDER BY embedding <=> :query_vector LIMIT :n"
    ), {"query_vector": embedding_str, "n": fetch_n}).fetchall()

    sparse_rows = session.execute(text(
        "SELECT id, document_id, chunk_text, page_number "
        "FROM chunks WHERE search_vector @@ plainto_tsquery('english', :q) "
        "ORDER BY ts_rank(search_vector, plainto_tsquery('english', :q)) DESC LIMIT :n"
    ), {"q": query_text, "n": fetch_n}).fetchall()

    fused_scores: dict[int, float] = {}
    row_by_id: dict[int, tuple] = {}
    for rank, row in enumerate(dense_rows):
        fused_scores[row.id] = fused_scores.get(row.id, 0.0) + 1.0 / (RRF_K + rank + 1)
        row_by_id[row.id] = row
    for rank, row in enumerate(sparse_rows):
        fused_scores[row.id] = fused_scores.get(row.id, 0.0) + 1.0 / (RRF_K + rank + 1)
        row_by_id[row.id] = row

    ranked_ids = sorted(fused_scores, key=lambda cid: fused_scores[cid], reverse=True)[:top_k]
    return [
        SearchResult(
            chunk_id=cid, document_id=row_by_id[cid].document_id,
            chunk_text=row_by_id[cid].chunk_text, page_number=row_by_id[cid].page_number,
            score=fused_scores[cid],
        )
        for cid in ranked_ids
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_hybrid_search.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/retrieval backend/tests/test_hybrid_search.py
git commit -m "feat: add hybrid dense+full-text search with reciprocal rank fusion"
```

---

### Task 12: Reconciliation Rules Module

**Files:**
- Create: `backend/app/reconciliation/__init__.py`
- Create: `backend/app/reconciliation/rules.py`
- Test: `backend/tests/test_reconciliation_rules.py`

**Interfaces:**
- Produces: `RuleLineItem` (dataclass: `description`, `category`, `amount`), `LineItemAdjustment` (dataclass: `description`, `original_amount`, `eligible_amount`, `deduction`), `apply_sub_limits(items, sub_limits) -> list[RuleLineItem]`, `compute_room_rent_proportionate_deduction(items, room_rent_limit_per_day, room_rent_charged_per_day) -> tuple[float, list[LineItemAdjustment]]`, `compute_admissible_amount(items, policy_rules: PolicyRuleExtraction, room_rent_charged_per_day) -> ReconciliationBreakdown` — Task 13 consumes these.

- [ ] **Step 1: Write the failing tests using the exact planted-discrepancy demo numbers**

```python
# backend/tests/test_reconciliation_rules.py
from app.reconciliation.rules import (
    RuleLineItem, apply_sub_limits, compute_room_rent_proportionate_deduction,
    compute_admissible_amount,
)
from app.ingestion.extraction import PolicyRuleExtraction

DEMO_ITEMS = [
    RuleLineItem(description="Room rent (5 days)", category="room_rent", amount=40000.0),
    RuleLineItem(description="OT charges", category="ot_charges", amount=30000.0),
    RuleLineItem(description="Doctor fees", category="doctor_fees", amount=15000.0),
    RuleLineItem(description="Nursing", category="nursing", amount=10000.0),
    RuleLineItem(description="Medicines", category="medicines", amount=12000.0),
    RuleLineItem(description="Consumables", category="consumables", amount=8000.0),
    RuleLineItem(description="Diagnostics", category="diagnostics", amount=5000.0),
]

def test_no_deduction_when_room_rent_within_limit():
    deduction, adjustments = compute_room_rent_proportionate_deduction(
        DEMO_ITEMS, room_rent_limit_per_day=8000.0, room_rent_charged_per_day=8000.0
    )
    assert deduction == 0.0
    assert adjustments == []

def test_proportionate_deduction_applies_only_to_room_linked_categories():
    deduction, adjustments = compute_room_rent_proportionate_deduction(
        DEMO_ITEMS, room_rent_limit_per_day=5000.0, room_rent_charged_per_day=8000.0
    )
    # ratio = 5000/8000 = 0.625; proportionate categories sum to 95000
    # eligible = 95000 * 0.625 = 59375; deduction = 95000 - 59375 = 35625
    assert round(deduction, 2) == 35625.0
    categories_adjusted = {a.description for a in adjustments}
    assert categories_adjusted == {"Room rent (5 days)", "OT charges", "Doctor fees", "Nursing"}

def test_sub_limits_cap_matching_category():
    items = [RuleLineItem(description="Cataract surgery", category="ot_charges", amount=60000.0)]
    capped = apply_sub_limits(items, {"ot_charges": 40000.0})
    assert capped[0].amount == 40000.0

def test_compute_admissible_amount_matches_hand_calculation():
    policy = PolicyRuleExtraction(
        sum_insured=500000.0, room_rent_limit_per_day=5000.0,
        room_rent_limit_type="fixed_amount", co_pay_percentage=10.0, sub_limits={},
    )
    breakdown = compute_admissible_amount(DEMO_ITEMS, policy, room_rent_charged_per_day=8000.0)

    assert round(breakdown.room_rent_deduction, 2) == 35625.0
    assert round(breakdown.admissible_before_copay, 2) == 84375.0
    assert round(breakdown.co_pay_deduction, 2) == 8437.5
    assert round(breakdown.computed_approved_amount, 2) == 75937.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_reconciliation_rules.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/app/reconciliation/__init__.py
```

```python
# backend/app/reconciliation/rules.py
from dataclasses import dataclass
from app.ingestion.extraction import PolicyRuleExtraction

PROPORTIONATE_CATEGORIES = {"room_rent", "ot_charges", "doctor_fees", "nursing"}

@dataclass
class RuleLineItem:
    description: str
    category: str
    amount: float

@dataclass
class LineItemAdjustment:
    description: str
    original_amount: float
    eligible_amount: float
    deduction: float

@dataclass
class ReconciliationBreakdown:
    room_rent_deduction: float
    room_rent_adjustments: list[LineItemAdjustment]
    admissible_before_copay: float
    co_pay_deduction: float
    computed_approved_amount: float

def apply_sub_limits(items: list[RuleLineItem], sub_limits: dict[str, float]) -> list[RuleLineItem]:
    result = []
    for item in items:
        limit = sub_limits.get(item.category)
        amount = min(item.amount, limit) if limit is not None else item.amount
        result.append(RuleLineItem(description=item.description, category=item.category, amount=amount))
    return result

def compute_room_rent_proportionate_deduction(
    items: list[RuleLineItem], room_rent_limit_per_day: float, room_rent_charged_per_day: float,
) -> tuple[float, list[LineItemAdjustment]]:
    if room_rent_charged_per_day <= room_rent_limit_per_day:
        return 0.0, []

    ratio = room_rent_limit_per_day / room_rent_charged_per_day
    adjustments = []
    total_deduction = 0.0
    for item in items:
        if item.category in PROPORTIONATE_CATEGORIES:
            eligible = item.amount * ratio
            deduction = item.amount - eligible
            total_deduction += deduction
            adjustments.append(LineItemAdjustment(
                description=item.description, original_amount=item.amount,
                eligible_amount=eligible, deduction=deduction,
            ))
    return total_deduction, adjustments

def compute_admissible_amount(
    items: list[RuleLineItem], policy_rules: PolicyRuleExtraction, room_rent_charged_per_day: float,
) -> ReconciliationBreakdown:
    capped_items = apply_sub_limits(items, policy_rules.sub_limits)

    room_rent_deduction = 0.0
    room_rent_adjustments: list[LineItemAdjustment] = []
    if policy_rules.room_rent_limit_type == "fixed_amount" and policy_rules.room_rent_limit_per_day:
        room_rent_deduction, room_rent_adjustments = compute_room_rent_proportionate_deduction(
            capped_items, policy_rules.room_rent_limit_per_day, room_rent_charged_per_day,
        )

    total_before_deduction = sum(i.amount for i in capped_items)
    admissible_before_copay = total_before_deduction - room_rent_deduction
    co_pay_deduction = admissible_before_copay * (policy_rules.co_pay_percentage / 100.0)
    computed_approved_amount = admissible_before_copay - co_pay_deduction

    return ReconciliationBreakdown(
        room_rent_deduction=room_rent_deduction,
        room_rent_adjustments=room_rent_adjustments,
        admissible_before_copay=admissible_before_copay,
        co_pay_deduction=co_pay_deduction,
        computed_approved_amount=computed_approved_amount,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_reconciliation_rules.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/reconciliation backend/tests/test_reconciliation_rules.py
git commit -m "feat: add deterministic mediclaim reconciliation rules"
```

---

### Task 13: Reconciliation Engine (`reconcile_claim`)

**Files:**
- Create: `backend/app/reconciliation/engine.py`
- Test: `backend/tests/test_reconciliation_engine.py`

**Interfaces:**
- Consumes: `LineItem`, `PolicyRule`, `Document` models (Task 2), `compute_admissible_amount` (Task 12).
- Produces: `reconcile_claim(session) -> ReconciliationReport | None` where `ReconciliationReport` has `.computed_approved_amount`, `.actual_approved_amount`, `.discrepancy`, `.breakdown`, `.matches: bool` (returns `None` when bill, policy, or settlement is missing). Task 14 consumes this.

- [ ] **Step 1: Write the failing test using the planted-discrepancy scenario**

```python
# backend/tests/test_reconciliation_engine.py
from app.db.models import Document, LineItem, PolicyRule
from app.reconciliation.engine import reconcile_claim

def _seed_full_claim(session):
    bill = Document(doc_type="bill", filename="bill.pdf", status="indexed")
    policy = Document(doc_type="policy", filename="policy.pdf", status="indexed")
    settlement = Document(doc_type="settlement", filename="settlement.pdf", status="indexed")
    session.add_all([bill, policy, settlement])
    session.commit()

    items = [
        ("Room rent (5 days)", "room_rent", 40000.0),
        ("OT charges", "ot_charges", 30000.0),
        ("Doctor fees", "doctor_fees", 15000.0),
        ("Nursing", "nursing", 10000.0),
        ("Medicines", "medicines", 12000.0),
        ("Consumables", "consumables", 8000.0),
        ("Diagnostics", "diagnostics", 5000.0),
    ]
    for desc, category, amount in items:
        session.add(LineItem(document_id=bill.id, description=desc, category=category, amount=amount))

    session.add(PolicyRule(
        document_id=policy.id, sum_insured=500000.0, room_rent_limit_per_day=5000.0,
        room_rent_limit_type="fixed_amount", co_pay_percentage=10.0, sub_limits={},
    ))

    session.add(LineItem(
        document_id=settlement.id, description="Overall settlement", category="settlement_line",
        amount=120000.0, claimed_amount=120000.0, approved_amount=70000.0,
        deducted_amount=50000.0, deduction_reason="Room rent proportionate deduction and co-payment",
    ))
    session.commit()
    return bill, policy, settlement

def test_reconcile_claim_flags_planted_discrepancy(db_session):
    _seed_full_claim(db_session)

    report = reconcile_claim(db_session)

    assert report is not None
    assert round(report.computed_approved_amount, 2) == 75937.5
    assert report.actual_approved_amount == 70000.0
    assert round(report.discrepancy, 2) == 5937.5
    assert report.matches is False

def test_reconcile_claim_returns_none_when_documents_missing(db_session):
    bill = Document(doc_type="bill", filename="bill.pdf", status="indexed")
    db_session.add(bill)
    db_session.commit()

    assert reconcile_claim(db_session) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_reconciliation_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/app/reconciliation/engine.py
from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.db.models import Document, LineItem, PolicyRule
from app.ingestion.extraction import PolicyRuleExtraction
from app.reconciliation.rules import RuleLineItem, compute_admissible_amount, ReconciliationBreakdown

TOLERANCE = 1.0

@dataclass
class ReconciliationReport:
    computed_approved_amount: float
    actual_approved_amount: float
    discrepancy: float
    breakdown: ReconciliationBreakdown
    matches: bool

def _active_document(session: Session, doc_type: str) -> Document | None:
    return session.query(Document).filter(
        Document.doc_type == doc_type, Document.status == "indexed"
    ).first()

def reconcile_claim(session: Session) -> ReconciliationReport | None:
    bill = _active_document(session, "bill")
    policy = _active_document(session, "policy")
    settlement = _active_document(session, "settlement")
    if not (bill and policy and settlement):
        return None

    bill_items = session.query(LineItem).filter_by(document_id=bill.id).all()
    policy_rule = session.query(PolicyRule).filter_by(document_id=policy.id).first()
    settlement_items = session.query(LineItem).filter_by(document_id=settlement.id).all()
    if not (bill_items and policy_rule and settlement_items):
        return None

    room_rent_items = [i for i in bill_items if i.category == "room_rent"]
    room_rent_charged_per_day = float(room_rent_items[0].amount) / 5 if room_rent_items else 0.0
    # NOTE: days_admitted is not yet modeled as a discrete field (see Open Risks in
    # the spec); for the single-room-rent-line-item case this divides by the fixed
    # 5-day demo stay. A future task could extract `days_admitted` explicitly.

    rule_items = [RuleLineItem(description=i.description, category=i.category, amount=float(i.amount)) for i in bill_items]
    policy_extraction = PolicyRuleExtraction(
        sum_insured=float(policy_rule.sum_insured),
        room_rent_limit_per_day=float(policy_rule.room_rent_limit_per_day) if policy_rule.room_rent_limit_per_day else None,
        room_rent_limit_type=policy_rule.room_rent_limit_type,
        co_pay_percentage=float(policy_rule.co_pay_percentage),
        sub_limits=policy_rule.sub_limits or {},
    )

    breakdown = compute_admissible_amount(rule_items, policy_extraction, room_rent_charged_per_day)

    actual_approved = sum(float(i.approved_amount) for i in settlement_items if i.approved_amount is not None)
    discrepancy = breakdown.computed_approved_amount - actual_approved

    return ReconciliationReport(
        computed_approved_amount=breakdown.computed_approved_amount,
        actual_approved_amount=actual_approved,
        discrepancy=discrepancy,
        breakdown=breakdown,
        matches=abs(discrepancy) <= TOLERANCE,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_reconciliation_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/reconciliation/engine.py backend/tests/test_reconciliation_engine.py
git commit -m "feat: add DB-backed reconciliation engine"
```

---

### Task 14: Agent Tools (`search_docs`, `reconcile_claim`)

**Files:**
- Create: `backend/app/agent/__init__.py`
- Create: `backend/app/agent/tools.py`
- Test: `backend/tests/test_agent_tools.py`

**Interfaces:**
- Consumes: `hybrid_search` (Task 11), `embed_query` (Task 5), `reconcile_claim` engine (Task 13), `Document` model for filename/page lookups (Task 2).
- Produces: `make_search_docs_tool(session)`, `make_reconcile_claim_tool(session)` — each returns a `@beta_tool`-decorated function bound to that session. Task 15 consumes these.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_agent_tools.py
import json
from unittest.mock import patch
from app.db.models import Document, Chunk, LineItem, PolicyRule
from app.agent.tools import make_search_docs_tool, make_reconcile_claim_tool

def test_search_docs_tool_returns_chunk_ids_and_text(db_session):
    doc = Document(doc_type="policy", filename="policy.pdf", status="indexed")
    db_session.add(doc)
    db_session.commit()
    chunk = Chunk(
        document_id=doc.id, chunk_text="Room rent limit is Rs 5000/day",
        contextual_text="Room rent limit is Rs 5000/day", page_number=3,
        embedding=[0.1] * 1024,
    )
    db_session.add(chunk)
    db_session.commit()
    from sqlalchemy import text
    db_session.execute(text("UPDATE chunks SET search_vector = to_tsvector('english', chunk_text)"))
    db_session.commit()

    with patch("app.agent.tools.embed_query", return_value=[0.1] * 1024):
        search_docs = make_search_docs_tool(db_session)
        result = search_docs(query="room rent limit")

    parsed = json.loads(result)
    assert len(parsed) == 1
    assert parsed[0]["chunk_id"] == chunk.id
    assert parsed[0]["doc_type"] == "policy"
    assert parsed[0]["page_number"] == 3
    assert "Room rent limit" in parsed[0]["text"]

def test_reconcile_claim_tool_reports_discrepancy(db_session):
    bill = Document(doc_type="bill", filename="bill.pdf", status="indexed")
    policy = Document(doc_type="policy", filename="policy.pdf", status="indexed")
    settlement = Document(doc_type="settlement", filename="settlement.pdf", status="indexed")
    db_session.add_all([bill, policy, settlement])
    db_session.commit()
    db_session.add(LineItem(document_id=bill.id, description="Room rent (5 days)", category="room_rent", amount=40000.0))
    db_session.add(PolicyRule(
        document_id=policy.id, sum_insured=500000.0, room_rent_limit_per_day=5000.0,
        room_rent_limit_type="fixed_amount", co_pay_percentage=10.0, sub_limits={},
    ))
    db_session.add(LineItem(
        document_id=settlement.id, description="Overall settlement", category="settlement_line",
        amount=40000.0, claimed_amount=40000.0, approved_amount=20000.0, deducted_amount=20000.0,
    ))
    db_session.commit()

    reconcile = make_reconcile_claim_tool(db_session)
    result = reconcile()

    parsed = json.loads(result)
    assert parsed["matches"] is False
    assert "discrepancy" in parsed

def test_reconcile_claim_tool_reports_missing_documents(db_session):
    reconcile = make_reconcile_claim_tool(db_session)
    result = reconcile()
    parsed = json.loads(result)
    assert parsed["error"] == "missing_documents"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_agent_tools.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/app/agent/__init__.py
```

```python
# backend/app/agent/tools.py
import json
from dataclasses import asdict
from anthropic import beta_tool
from sqlalchemy.orm import Session
from app.db.models import Document
from app.ingestion.embeddings import embed_query
from app.retrieval.hybrid_search import hybrid_search
from app.reconciliation.engine import reconcile_claim as run_reconciliation

def make_search_docs_tool(session: Session):
    @beta_tool
    def search_docs(query: str) -> str:
        """Search the uploaded bill, policy, and settlement documents for text
        relevant to the query. Always pass a standalone, self-contained query
        string — resolve pronouns and prior context yourself before calling
        this tool.

        Args:
            query: A self-contained search query, e.g. "room rent limit per day".
        """
        query_embedding = embed_query(query)
        results = hybrid_search(session, query, query_embedding, top_k=8)
        payload = []
        for r in results:
            doc = session.get(Document, r.document_id)
            payload.append({
                "chunk_id": r.chunk_id,
                "doc_type": doc.doc_type if doc else None,
                "filename": doc.filename if doc else None,
                "page_number": r.page_number,
                "text": r.chunk_text,
            })
        return json.dumps(payload)

    return search_docs

def make_reconcile_claim_tool(session: Session):
    @beta_tool
    def reconcile_claim() -> str:
        """Recompute what the insurance settlement should be from the bill's
        line items and the policy's actual rules (room rent proportionate
        deduction, co-payment, sub-limits), and compare it against what the
        settlement letter actually approved. Use this whenever the user asks
        why a deduction happened or whether their settlement is correct."""
        report = run_reconciliation(session)
        if report is None:
            return json.dumps({
                "error": "missing_documents",
                "message": "Need an indexed bill, policy, and settlement letter to reconcile.",
            })
        return json.dumps({
            "computed_approved_amount": round(report.computed_approved_amount, 2),
            "actual_approved_amount": round(report.actual_approved_amount, 2),
            "discrepancy": round(report.discrepancy, 2),
            "matches": report.matches,
            "room_rent_deduction": round(report.breakdown.room_rent_deduction, 2),
            "co_pay_deduction": round(report.breakdown.co_pay_deduction, 2),
            "room_rent_adjustments": [asdict(a) for a in report.breakdown.room_rent_adjustments],
        })

    return reconcile_claim
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_agent_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/tools.py backend/app/agent/__init__.py backend/tests/test_agent_tools.py
git commit -m "feat: add search_docs and reconcile_claim agent tools"
```

---

### Task 15: Agent Chat Loop

**Files:**
- Create: `backend/app/agent/chat.py`
- Test: `backend/tests/test_agent_chat.py`

**Interfaces:**
- Consumes: `make_search_docs_tool`, `make_reconcile_claim_tool` (Task 14).
- Produces: `stream_agent_response(session, history: list[dict], user_message: str) -> Iterator[str]` (yields text chunks) and, after full consumption, exposes the final raw text via `get_last_full_text()` on the same module — Task 16 consumes this to persist the assistant message.

- [ ] **Step 1: Write the failing test with a mocked tool runner**

```python
# backend/tests/test_agent_chat.py
from unittest.mock import patch, MagicMock
from app.agent.chat import stream_agent_response

class _FakeStream:
    def __init__(self, text_chunks):
        self.text_stream = iter(text_chunks)

    def get_final_message(self):
        return MagicMock(stop_reason="end_turn")

def test_stream_agent_response_yields_text_chunks(db_session):
    fake_stream = _FakeStream(["The room rent ", "was deducted because [[42]]."])

    with patch("app.agent.chat._client") as mock_client:
        mock_client.beta.messages.tool_runner.return_value = iter([fake_stream])

        chunks = list(stream_agent_response(db_session, history=[], user_message="Why was I charged less?"))

    assert "".join(chunks) == "The room rent was deducted because [[42]]."
    call_kwargs = mock_client.beta.messages.tool_runner.call_args.kwargs
    assert call_kwargs["model"] == "claude-opus-5"
    assert call_kwargs["stream"] is True
    assert len(call_kwargs["tools"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_agent_chat.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/app/agent/chat.py
from typing import Iterator
import anthropic
from sqlalchemy.orm import Session
from app.config import settings
from app.agent.tools import make_search_docs_tool, make_reconcile_claim_tool

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

SYSTEM_PROMPT = """You help someone understand their Indian mediclaim health \
insurance claim. You have two tools: `search_docs` to find relevant text in \
their uploaded bill, policy, and settlement letter, and `reconcile_claim` to \
recompute whether the settlement math is correct.

Rules:
- Always call `search_docs` with a complete, standalone query — never a bare \
  pronoun or fragment like "that one"; resolve it from the conversation \
  yourself first.
- When the user asks why a deduction happened or whether it's correct, call \
  `reconcile_claim`.
- Every factual claim sourced from a retrieved chunk must be followed by \
  `[[chunk_id]]` using the chunk_id from that search_docs result.
- If neither tool grounds an answer, say so plainly and suggest contacting \
  the insurer directly. Never guess or fabricate a figure or clause."""

def stream_agent_response(session: Session, history: list[dict], user_message: str) -> Iterator[str]:
    tools = [make_search_docs_tool(session), make_reconcile_claim_tool(session)]
    messages = history + [{"role": "user", "content": user_message}]

    runner = _client.beta.messages.tool_runner(
        model="claude-opus-5",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        tools=tools,
        messages=messages,
        stream=True,
    )
    for stream in runner:
        for text in stream.text_stream:
            yield text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_agent_chat.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/chat.py backend/tests/test_agent_chat.py
git commit -m "feat: add streaming Claude Opus 5 agent chat loop with tool use"
```

---

### Task 16: Chat API and Persistence

**Files:**
- Create: `backend/app/api/chat.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_chat_api.py`

**Interfaces:**
- Consumes: `stream_agent_response` (Task 15), `Message`, `Chunk`, `Document` models (Task 2).
- Produces: `POST /chat/message` (SSE stream of `{"type": "token", "text": ...}` then a final `{"type": "done", "content": ..., "citations": [...]}`), `GET /chat/history` — Task 19 (frontend) consumes these.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_chat_api.py
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.db.models import Document, Chunk, Message

def test_post_chat_message_streams_and_persists_with_citations(db_session, monkeypatch):
    monkeypatch.setattr("app.api.chat.SessionLocal", lambda: db_session)
    doc = Document(doc_type="policy", filename="policy.pdf", status="indexed")
    db_session.add(doc)
    db_session.commit()
    db_session.add(Chunk(document_id=doc.id, chunk_text="Room rent capped at Rs 5000", contextual_text="x", page_number=4))
    db_session.commit()
    chunk_id = db_session.query(Chunk).first().id

    def fake_stream(session, history, user_message):
        yield f"Your room rent was capped [[{chunk_id}]]."

    client = TestClient(app)
    with patch("app.api.chat.stream_agent_response", side_effect=fake_stream):
        with client.stream("POST", "/chat/message", json={"message": "Why was my room rent capped?"}) as response:
            events = [json.loads(line[len("data: "):]) for line in response.iter_lines() if line.startswith("data: ")]

    done_event = next(e for e in events if e["type"] == "done")
    assert done_event["content"] == "Your room rent was capped [1]."
    assert done_event["citations"] == [{"number": 1, "chunk_id": chunk_id, "doc_type": "policy", "filename": "policy.pdf", "page_number": 4}]

    messages = db_session.query(Message).order_by(Message.id).all()
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].citations == done_event["citations"]

def test_get_chat_history_returns_persisted_messages(db_session, monkeypatch):
    monkeypatch.setattr("app.api.chat.SessionLocal", lambda: db_session)
    db_session.add(Message(role="user", content="Hi"))
    db_session.add(Message(role="assistant", content="Hello, how can I help?"))
    db_session.commit()

    client = TestClient(app)
    response = client.get("/chat/history")

    assert response.status_code == 200
    body = response.json()
    assert [m["role"] for m in body] == ["user", "assistant"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_chat_api.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/app/api/chat.py
import json
import re
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.db.session import SessionLocal, get_engine
from app.db.models import Message, Chunk, Document
from app.agent.chat import stream_agent_response

get_engine()
router = APIRouter(prefix="/chat", tags=["chat"])

CITATION_PATTERN = re.compile(r"\[\[(\d+)\]\]")

class ChatRequest(BaseModel):
    message: str

def _resolve_citations(session, raw_text: str) -> tuple[str, list[dict]]:
    citations = []
    seen: dict[int, int] = {}

    def replace(match: re.Match) -> str:
        chunk_id = int(match.group(1))
        if chunk_id not in seen:
            chunk = session.get(Chunk, chunk_id)
            if chunk is None:
                return ""
            document = session.get(Document, chunk.document_id)
            number = len(seen) + 1
            seen[chunk_id] = number
            citations.append({
                "number": number, "chunk_id": chunk_id,
                "doc_type": document.doc_type if document else None,
                "filename": document.filename if document else None,
                "page_number": chunk.page_number,
            })
        return f"[{seen[chunk_id]}]"

    cleaned_text = CITATION_PATTERN.sub(replace, raw_text)
    return cleaned_text, citations

@router.post("/message")
def post_chat_message(request: ChatRequest):
    session = SessionLocal()

    def event_stream():
        try:
            history = [
                {"role": m.role, "content": m.content}
                for m in session.query(Message).order_by(Message.id).all()
            ]
            session.add(Message(role="user", content=request.message))
            session.commit()

            raw_chunks = []
            for token in stream_agent_response(session, history, request.message):
                raw_chunks.append(token)
                yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"

            raw_text = "".join(raw_chunks)
            cleaned_text, citations = _resolve_citations(session, raw_text)

            session.add(Message(role="assistant", content=cleaned_text, citations=citations))
            session.commit()

            yield f"data: {json.dumps({'type': 'done', 'content': cleaned_text, 'citations': citations})}\n\n"
        finally:
            session.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.get("/history")
def get_chat_history():
    session = SessionLocal()
    try:
        messages = session.query(Message).order_by(Message.id).all()
        return [
            {"id": m.id, "role": m.role, "content": m.content, "citations": m.citations}
            for m in messages
        ]
    finally:
        session.close()
```

- [ ] **Step 4: Mount the router**

```python
# backend/app/main.py — add these lines
from app.api.chat import router as chat_router

app.include_router(chat_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_chat_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/chat.py backend/app/main.py backend/tests/test_chat_api.py
git commit -m "feat: add streaming chat API with server-side citation resolution and persistence"
```

---

### Task 17: Frontend Scaffolding

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/App.tsx`
- Test: `frontend/src/__tests__/App.test.tsx`

**Interfaces:**
- Produces: `Document`, `ChatMessage`, `Citation` TypeScript types (`src/types.ts`); `listDocuments()`, `uploadDocument(file, docType)`, `deleteDocument(id)`, `getChatHistory()`, `streamChatMessage(message, onToken, onDone)` (`src/api/client.ts`) — Tasks 18-19 consume these.

- [ ] **Step 1: Create `package.json`**

```json
{
  "name": "mediclaim-clarity-frontend",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.0.1",
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.3",
    "jsdom": "^25.0.1",
    "typescript": "^5.6.3",
    "vite": "^5.4.10",
    "vitest": "^2.1.4"
  }
}
```

- [ ] **Step 2: Create Vite/TS config and HTML shell**

```typescript
// frontend/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/documents': 'http://localhost:8000', '/chat': 'http://localhost:8000' } },
  test: { environment: 'jsdom', globals: true },
})
```

```json
// frontend/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["ES2020", "DOM"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true
  },
  "include": ["src"]
}
```

```html
<!-- frontend/index.html -->
<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8" /><title>Mediclaim Claim Clarity</title></head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 3: Create types and API client**

```typescript
// frontend/src/types.ts
export interface DocumentRecord {
  id: number
  doc_type: 'bill' | 'policy' | 'settlement'
  filename: string
  status: 'processing' | 'indexed' | 'failed'
}

export interface Citation {
  number: number
  chunk_id: number
  doc_type: string
  filename: string
  page_number: number | null
}

export interface ChatMessage {
  id?: number
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
}
```

```typescript
// frontend/src/api/client.ts
import type { DocumentRecord, ChatMessage, Citation } from '../types'

export async function listDocuments(): Promise<DocumentRecord[]> {
  const res = await fetch('/documents')
  return res.json()
}

export async function uploadDocument(file: File, docType: string): Promise<DocumentRecord> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('doc_type', docType)
  const res = await fetch('/documents', { method: 'POST', body: formData })
  if (!res.ok) throw new Error((await res.json()).detail ?? 'Upload failed')
  return res.json()
}

export async function deleteDocument(id: number): Promise<void> {
  await fetch(`/documents/${id}`, { method: 'DELETE' })
}

export async function getChatHistory(): Promise<ChatMessage[]> {
  const res = await fetch('/chat/history')
  return res.json()
}

export async function streamChatMessage(
  message: string,
  onToken: (text: string) => void,
  onDone: (content: string, citations: Citation[]) => void,
): Promise<void> {
  const res = await fetch('/chat/message', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const event = JSON.parse(line.slice('data: '.length))
      if (event.type === 'token') onToken(event.text)
      if (event.type === 'done') onDone(event.content, event.citations)
    }
  }
}
```

- [ ] **Step 4: Write the failing App test**

```tsx
// frontend/src/__tests__/App.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import App from '../App'

describe('App', () => {
  it('renders the document sidebar and chat panel regions', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: /documents/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /chat/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 5: Install dependencies and run test to verify it fails**

Run: `cd frontend && npm install && npm test`
Expected: FAIL — `Cannot find module '../App'`

- [ ] **Step 6: Implement `App.tsx` and `main.tsx`**

```tsx
// frontend/src/App.tsx
export default function App() {
  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <aside style={{ width: 280, borderRight: '1px solid #ddd', padding: 16 }}>
        <h2>Documents</h2>
      </aside>
      <main style={{ flex: 1, padding: 16 }}>
        <h2>Chat</h2>
      </main>
    </div>
  )
}
```

```tsx
// frontend/src/main.tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/
git commit -m "chore: scaffold React+Vite+TS frontend with API client"
```

---

### Task 18: Document Sidebar Component

**Files:**
- Create: `frontend/src/components/DocumentSidebar.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/__tests__/DocumentSidebar.test.tsx`

**Interfaces:**
- Consumes: `listDocuments`, `uploadDocument`, `deleteDocument` (Task 17), `DocumentRecord` type.
- Produces: `<DocumentSidebar />` component — mounted by `App.tsx`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/DocumentSidebar.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import DocumentSidebar from '../components/DocumentSidebar'
import * as api from '../api/client'

beforeEach(() => {
  vi.spyOn(api, 'listDocuments').mockResolvedValue([
    { id: 1, doc_type: 'bill', filename: 'bill.pdf', status: 'indexed' },
  ])
})

describe('DocumentSidebar', () => {
  it('lists uploaded documents and deletes on click', async () => {
    const deleteSpy = vi.spyOn(api, 'deleteDocument').mockResolvedValue(undefined)
    render(<DocumentSidebar />)

    expect(await screen.findByText('bill.pdf')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /delete bill.pdf/i }))

    await waitFor(() => expect(deleteSpy).toHaveBeenCalledWith(1))
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module '../components/DocumentSidebar'`

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/DocumentSidebar.tsx
import { useEffect, useState } from 'react'
import type { DocumentRecord } from '../types'
import { listDocuments, uploadDocument, deleteDocument } from '../api/client'

const DOC_TYPES: DocumentRecord['doc_type'][] = ['bill', 'policy', 'settlement']

export default function DocumentSidebar() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [error, setError] = useState<string | null>(null)

  const refresh = () => listDocuments().then(setDocuments)

  useEffect(() => {
    refresh()
  }, [])

  const handleUpload = async (docType: DocumentRecord['doc_type'], file: File) => {
    setError(null)
    try {
      await uploadDocument(file, docType)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const handleDelete = async (id: number) => {
    await deleteDocument(id)
    await refresh()
  }

  return (
    <div>
      <h2>Documents</h2>
      {error && <p role="alert" style={{ color: 'red' }}>{error}</p>}
      {DOC_TYPES.map((docType) => (
        <div key={docType} style={{ marginBottom: 12 }}>
          <label>
            {docType}
            <input
              type="file"
              accept="application/pdf"
              onChange={(e) => e.target.files?.[0] && handleUpload(docType, e.target.files[0])}
            />
          </label>
        </div>
      ))}
      <ul>
        {documents.map((doc) => (
          <li key={doc.id}>
            {doc.filename} ({doc.status})
            <button aria-label={`delete ${doc.filename}`} onClick={() => handleDelete(doc.id)}>
              Delete
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
```

- [ ] **Step 4: Mount it in `App.tsx`**

```tsx
// frontend/src/App.tsx
import DocumentSidebar from './components/DocumentSidebar'

export default function App() {
  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <aside style={{ width: 280, borderRight: '1px solid #ddd', padding: 16 }}>
        <DocumentSidebar />
      </aside>
      <main style={{ flex: 1, padding: 16 }}>
        <h2>Chat</h2>
      </main>
    </div>
  )
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DocumentSidebar.tsx frontend/src/App.tsx frontend/src/__tests__/DocumentSidebar.test.tsx
git commit -m "feat: add document sidebar with upload and delete"
```

---

### Task 19: Chat Panel Component

**Files:**
- Create: `frontend/src/components/ChatPanel.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/__tests__/ChatPanel.test.tsx`

**Interfaces:**
- Consumes: `getChatHistory`, `streamChatMessage` (Task 17), `ChatMessage`/`Citation` types.
- Produces: `<ChatPanel />` component — mounted by `App.tsx`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/ChatPanel.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ChatPanel from '../components/ChatPanel'
import * as api from '../api/client'

beforeEach(() => {
  vi.spyOn(api, 'getChatHistory').mockResolvedValue([])
})

describe('ChatPanel', () => {
  it('sends a message and renders the streamed response with citations', async () => {
    vi.spyOn(api, 'streamChatMessage').mockImplementation(async (_msg, onToken, onDone) => {
      onToken('Your room rent was capped ')
      onToken('[1].')
      onDone('Your room rent was capped [1].', [
        { number: 1, chunk_id: 42, doc_type: 'policy', filename: 'policy.pdf', page_number: 4 },
      ])
    })
    render(<ChatPanel />)

    fireEvent.change(screen.getByPlaceholderText(/ask a question/i), { target: { value: 'Why?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    await waitFor(() => expect(screen.getByText(/Your room rent was capped \[1\]\./)).toBeInTheDocument())
    expect(screen.getByText(/policy.pdf.*page 4/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module '../components/ChatPanel'`

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/ChatPanel.tsx
import { useEffect, useRef, useState } from 'react'
import type { ChatMessage } from '../types'
import { getChatHistory, streamChatMessage } from '../api/client'

export default function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const streamingIndex = useRef<number | null>(null)

  useEffect(() => {
    getChatHistory().then(setMessages)
  }, [])

  const send = async () => {
    if (!input.trim()) return
    const userMessage: ChatMessage = { role: 'user', content: input }
    const assistantIndex = messages.length + 1
    streamingIndex.current = assistantIndex
    setMessages((prev) => [...prev, userMessage, { role: 'assistant', content: '' }])
    setInput('')

    await streamChatMessage(
      userMessage.content,
      (token) => {
        setMessages((prev) => {
          const next = [...prev]
          next[assistantIndex] = { ...next[assistantIndex], content: next[assistantIndex].content + token }
          return next
        })
      },
      (content, citations) => {
        setMessages((prev) => {
          const next = [...prev]
          next[assistantIndex] = { role: 'assistant', content, citations }
          return next
        })
      },
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <h2>Chat</h2>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {messages.map((m, i) => (
          <div key={i} style={{ marginBottom: 8 }}>
            <strong>{m.role === 'user' ? 'You' : 'Assistant'}:</strong> {m.content}
            {m.citations && m.citations.length > 0 && (
              <ul>
                {m.citations.map((c) => (
                  <li key={c.chunk_id}>
                    [{c.number}] {c.filename} ({c.doc_type}), page {c.page_number}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      <div>
        <input
          placeholder="Ask a question about your claim"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
        />
        <button onClick={send}>Send</button>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Mount it in `App.tsx`**

```tsx
// frontend/src/App.tsx
import DocumentSidebar from './components/DocumentSidebar'
import ChatPanel from './components/ChatPanel'

export default function App() {
  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <aside style={{ width: 280, borderRight: '1px solid #ddd', padding: 16 }}>
        <DocumentSidebar />
      </aside>
      <main style={{ flex: 1, padding: 16 }}>
        <ChatPanel />
      </main>
    </div>
  )
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx frontend/src/App.tsx frontend/src/__tests__/ChatPanel.test.tsx
git commit -m "feat: add chat panel with streaming responses and citation display"
```

---

### Task 20: Synthetic Sample Data Generator

**Files:**
- Create: `backend/scripts/generate_sample_data.py`
- Test: `backend/tests/test_generate_sample_data.py`

**Interfaces:**
- Produces: `generate_sample_documents(output_dir: str) -> dict[str, str]` (returns `{"bill": path, "policy": path, "settlement": path}`) — Task 21 consumes this. Encodes the exact demo numbers used throughout this plan: sum insured ₹5,00,000, room rent limit ₹5,000/day, room rent charged ₹8,000/day over 5 days, co-pay 10%, computed correct approval ₹75,937.50, and a planted wrong settlement approval of ₹70,000 (discrepancy ₹5,937.50).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_generate_sample_data.py
import fitz
from app.ingestion.pdf_parser import parse_pdf
from scripts.generate_sample_data import generate_sample_documents

def test_generates_three_pdfs_with_expected_figures(tmp_path):
    paths = generate_sample_documents(str(tmp_path))

    assert set(paths.keys()) == {"bill", "policy", "settlement"}
    for path in paths.values():
        assert fitz.open(path).page_count >= 1

    bill_text = "\n".join(b.text for b in parse_pdf(paths["bill"]))
    assert "40,000" in bill_text or "40000" in bill_text

    policy_text = "\n".join(b.text for b in parse_pdf(paths["policy"]))
    assert "5,000" in policy_text or "5000" in policy_text
    assert "10%" in policy_text

    settlement_text = "\n".join(b.text for b in parse_pdf(paths["settlement"]))
    assert "70,000" in settlement_text or "70000" in settlement_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_generate_sample_data.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/scripts/generate_sample_data.py
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

def _write_lines(path: str, title: str, lines: list[str]) -> None:
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    y = height - 72
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, y, title)
    y -= 30
    c.setFont("Helvetica", 11)
    for line in lines:
        if y < 72:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = height - 72
        c.drawString(72, y, line)
        y -= 18
    c.save()

def generate_sample_documents(output_dir: str) -> dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    bill_path = out / "sample_bill.pdf"
    _write_lines(str(bill_path), "APOLLO CITY HOSPITAL - FINAL BILL", [
        "Patient: Ramesh Kumar   Admission: 5 days   Room Category: Private Room",
        "",
        "Room rent (5 days x Rs 8,000/day): Rs 40,000",
        "OT charges: Rs 30,000",
        "Doctor fees: Rs 15,000",
        "Nursing charges: Rs 10,000",
        "Medicines: Rs 12,000",
        "Consumables: Rs 8,000",
        "Diagnostics (lab + radiology): Rs 5,000",
        "",
        "TOTAL BILL AMOUNT: Rs 1,20,000",
    ])

    policy_path = out / "sample_policy.pdf"
    _write_lines(str(policy_path), "SURAKSHA GOLD MEDICLAIM POLICY", [
        "Policy Holder: Ramesh Kumar   Sum Insured: Rs 5,00,000",
        "",
        "ROOM RENT LIMIT",
        "The Company shall pay room rent up to Rs 5,000 per day. Where the",
        "insured is admitted to a room exceeding this limit, associated",
        "medical expenses (room rent, OT charges, doctor fees, nursing) will",
        "be paid in the same proportion as this limit bears to the actual",
        "room rent charged.",
        "",
        "CO-PAYMENT",
        "A co-payment of 10% of the admissible claim amount applies to all",
        "hospitalization claims under this policy.",
        "",
        "SUB-LIMITS",
        "No procedure-specific sub-limits apply under this plan.",
    ])

    settlement_path = out / "sample_settlement.pdf"
    _write_lines(str(settlement_path), "MEDIASSIST TPA - CLAIM SETTLEMENT LETTER", [
        "Claim No: MC-2026-004521   Policy Holder: Ramesh Kumar",
        "",
        "Total amount claimed: Rs 1,20,000",
        "Total amount approved: Rs 70,000",
        "Total amount deducted: Rs 50,000",
        "",
        "Deduction reason: Room rent proportionate deduction as per policy",
        "terms, and applicable co-payment.",
    ])

    return {"bill": str(bill_path), "policy": str(policy_path), "settlement": str(settlement_path)}

if __name__ == "__main__":
    import sys
    paths = generate_sample_documents(sys.argv[1] if len(sys.argv) > 1 else "sample_data/generated")
    for doc_type, path in paths.items():
        print(f"{doc_type}: {path}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_generate_sample_data.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/generate_sample_data.py backend/tests/test_generate_sample_data.py
git commit -m "feat: add synthetic sample claim document generator with planted discrepancy"
```

---

### Task 21: End-to-End Demo Verification

**Files:**
- Create: `backend/tests/test_end_to_end.py`

**Interfaces:**
- Consumes: every prior backend task's public interface. This is the capstone integration test — no new production code, only a test that proves the assembled system works.

- [ ] **Step 1: Write the integration test**

This test requires real `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` values (it is the one place in this plan that calls the real APIs instead of mocking them) and is marked so it's skipped when keys are absent — everything up to here has been verified with mocks, so this test is specifically about proving real integration, not about re-testing logic already covered.

```python
# backend/tests/test_end_to_end.py
import os
import pytest
from app.db.models import Document
from app.ingestion.pipeline import ingest_document
from app.reconciliation.engine import reconcile_claim
from scripts.generate_sample_data import generate_sample_documents

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("VOYAGE_API_KEY")),
    reason="requires real ANTHROPIC_API_KEY and VOYAGE_API_KEY",
)

def test_full_pipeline_catches_planted_discrepancy(db_session, tmp_path):
    paths = generate_sample_documents(str(tmp_path))

    for doc_type, path in paths.items():
        doc = Document(doc_type=doc_type, filename=os.path.basename(path), status="processing")
        db_session.add(doc)
        db_session.commit()
        ingest_document(db_session, doc.id, doc_type, path)

    assert all(d.status == "indexed" for d in db_session.query(Document).all())

    report = reconcile_claim(db_session)

    assert report is not None
    assert round(report.computed_approved_amount, 2) == 75937.5
    assert report.actual_approved_amount == 70000.0
    assert round(report.discrepancy, 2) == 5937.5
    assert report.matches is False
```

- [ ] **Step 2: Run it with real API keys set**

Run: `cd backend && ANTHROPIC_API_KEY=<key> VOYAGE_API_KEY=<key> python -m pytest tests/test_end_to_end.py -v`
Expected: PASS. If extraction accuracy causes a near-miss (e.g. `computed_approved_amount` off by a few rupees due to the model reading "Rs 1,20,000" differently), inspect what `extract_bill`/`extract_policy_rules` actually returned and tighten the extraction prompts in Tasks 7-8 rather than loosening this test's assertions — the whole point of Task 20's planted numbers is that they're exact.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_end_to_end.py
git commit -m "test: add end-to-end verification that reconciliation catches the planted discrepancy"
```

---

### Task 22 (Optional / Stretch): Golden Eval Script

**Files:**
- Create: `backend/scripts/run_eval.py`

**Interfaces:**
- Consumes: `stream_agent_response` (Task 15), sample documents (Task 20).
- Produces: a CLI script printing pass/fail per question — no other task depends on this; skip it if time is short, per the spec's own "stretch, lower priority" framing.

- [ ] **Step 1: Write the eval script**

```python
# backend/scripts/run_eval.py
"""Run a small golden set of questions against the ingested sample claim and
report whether each answer contains the expected figure/keyword. Requires
sample documents already ingested (see Task 21) and real API keys set."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.session import SessionLocal, get_engine
from app.config import settings
from app.agent.chat import stream_agent_response

GOLDEN_SET = [
    ("What is my room rent limit per day?", "5,000"),
    ("Why was my claim approved for less than I claimed?", "room rent"),
    ("Is my settlement amount correct according to my policy?", "75,937"),
]

def main():
    get_engine(settings.database_url)
    session = SessionLocal()
    passed = 0
    for question, expected_fragment in GOLDEN_SET:
        answer = "".join(stream_agent_response(session, [], question))
        ok = expected_fragment.lower() in answer.lower()
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {question}\n  -> {answer[:200]}\n")
    print(f"{passed}/{len(GOLDEN_SET)} passed")
    session.close()

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it manually against the ingested sample claim**

Run: `cd backend && python scripts/run_eval.py`
Expected: Prints each question with PASS/FAIL and a summary line. This is a manual/demo tool, not part of the automated test suite.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/run_eval.py
git commit -m "chore: add golden eval script for manual demo verification"
```

---

## Self-Review

**Spec coverage:**
- Document upload/processing → Tasks 3, 9, 10.
- Parsing/chunking/embedding → Tasks 3, 4, 5, 6.
- Structured extraction (bill, settlement, policy rules) → Tasks 7, 8.
- Retrieval (hybrid search) → Task 11.
- Reconciliation engine → Tasks 12, 13.
- Agent + tools + citations → Tasks 14, 15, 16.
- Document management UI (upload/delete) → Task 18.
- Chat UI + persistence + citations rendering → Task 16 (backend), Task 19 (frontend).
- Sample data with planted discrepancy → Task 20.
- End-to-end proof → Task 21.
- Eval (spec's own stretch item) → Task 22, marked optional.
- "At most one active document per type" assumption → enforced in Task 10's `upload_document` (409 on duplicate).
- "Deleted docs excluded from future retrieval/reconciliation" → enforced structurally: Task 2's `ON DELETE CASCADE` removes chunks/line_items/policy_rules with the document, and Task 13's `reconcile_claim` only reads `status == "indexed"` documents that still exist.
- "Chat history persists, past messages not rewritten on delete" → Task 16 persists every message row permanently; nothing in the plan ever updates or deletes a `Message` row.

**Placeholder scan:** No TBD/TODO markers; every step has runnable code; no "similar to Task N" shortcuts — Task 8 fully repeats the extraction pattern from Task 7 rather than referencing it.

**Type consistency:** `LineItemCategory` values (`room_rent`, `ot_charges`, `doctor_fees`, `nursing`, `medicines`, `consumables`, `diagnostics`, `misc`) are used identically in Task 7's Pydantic model, Task 12's `PROPORTIONATE_CATEGORIES`, and Task 9's ingestion pipeline. `PolicyRuleExtraction` fields match between Task 8 (extraction), Task 12 (`compute_admissible_amount`'s signature), and Task 13 (`reconcile_claim`'s reconstruction from ORM rows). Tool return shapes in Task 14 (`chunk_id`, `doc_type`, `page_number`, `text`) match what Task 15's system prompt tells the agent to expect (`[[chunk_id]]`) and what Task 16's `_resolve_citations` looks up.
