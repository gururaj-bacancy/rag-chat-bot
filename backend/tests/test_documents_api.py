from unittest.mock import patch

import fitz
import pytest
from fastapi.testclient import TestClient

from app.db import session as db_session_module
from app.db.models import Chunk, Document
from app.main import app


def _make_pdf_bytes() -> bytes:
    """A real (tiny) PDF, generated the way Task 3's parser test does, so the
    upload's multipart body contains genuine PDF bytes rather than a fake
    placeholder."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Sample document text for ingestion.")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def pdf_bytes():
    return _make_pdf_bytes()


@pytest.fixture
def client(db_session):
    """A TestClient whose routes resolve their DB session to the exact same
    `db_session` fixture object, per Task 2's pattern (see conftest.py). This
    is a `unittest.mock.patch` on `app.api.documents`'s session-factory
    lookup (`db_session_module.get_session`), not a bare `SessionLocal`
    import, so it can't go stale relative to `session.py`'s guidance.
    """
    with patch.object(db_session_module, "get_session", return_value=db_session):
        yield TestClient(app)


def _upload(client, pdf_bytes, doc_type="policy", filename="sample.pdf"):
    return client.post(
        "/documents",
        files={"file": (filename, pdf_bytes, "application/pdf")},
        data={"doc_type": doc_type},
    )


def test_upload_document_succeeds_and_triggers_ingestion(client, db_session, pdf_bytes):
    with patch("app.api.documents.ingest_document") as mock_ingest:
        response = _upload(client, pdf_bytes, doc_type="policy", filename="my-policy.pdf")

    assert response.status_code == 201
    body = response.json()
    assert body["doc_type"] == "policy"
    assert body["filename"] == "my-policy.pdf"
    assert body["status"] == "processing"
    assert "id" in body

    mock_ingest.assert_called_once()
    call_args = mock_ingest.call_args.args
    assert call_args[0] is db_session
    assert call_args[1] == body["id"]
    assert call_args[2] == "policy"
    assert isinstance(call_args[3], str) and call_args[3].endswith(".pdf")

    document = db_session.query(Document).filter_by(id=body["id"]).one()
    assert document.filename == "my-policy.pdf"
    assert document.doc_type == "policy"


def test_upload_rejects_duplicate_active_document(client, db_session, pdf_bytes):
    existing = Document(doc_type="bill", filename="first-bill.pdf", status="processing")
    db_session.add(existing)
    db_session.commit()

    with patch("app.api.documents.ingest_document") as mock_ingest:
        response = _upload(client, pdf_bytes, doc_type="bill", filename="second-bill.pdf")

    assert response.status_code == 409
    assert str(existing.id) in response.json()["detail"]
    mock_ingest.assert_not_called()

    count = db_session.query(Document).filter_by(doc_type="bill").count()
    assert count == 1


def test_upload_allowed_when_existing_of_same_type_has_failed(client, db_session, pdf_bytes):
    failed = Document(doc_type="settlement", filename="bad.pdf", status="failed")
    db_session.add(failed)
    db_session.commit()

    with patch("app.api.documents.ingest_document") as mock_ingest:
        response = _upload(client, pdf_bytes, doc_type="settlement", filename="retry.pdf")

    assert response.status_code == 201
    mock_ingest.assert_called_once()


def test_upload_rejects_invalid_doc_type(client, pdf_bytes):
    with patch("app.api.documents.ingest_document") as mock_ingest:
        response = _upload(client, pdf_bytes, doc_type="invoice")

    assert response.status_code == 400
    mock_ingest.assert_not_called()


def test_list_documents_returns_uploaded_documents(client, db_session):
    db_session.add_all(
        [
            Document(doc_type="policy", filename="policy.pdf", status="indexed"),
            Document(doc_type="bill", filename="bill.pdf", status="processing"),
        ]
    )
    db_session.commit()

    response = client.get("/documents")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    filenames = {d["filename"] for d in body}
    assert filenames == {"policy.pdf", "bill.pdf"}


def test_delete_document_cascades_to_chunks(client, db_session):
    document = Document(doc_type="policy", filename="to-delete.pdf", status="indexed")
    db_session.add(document)
    db_session.commit()

    chunk = Chunk(
        document_id=document.id,
        chunk_text="some chunk text",
        contextual_text="contextualized chunk text",
        page_number=1,
    )
    db_session.add(chunk)
    db_session.commit()
    document_id = document.id

    response = client.delete(f"/documents/{document_id}")

    assert response.status_code == 204
    assert db_session.query(Document).filter_by(id=document_id).first() is None
    assert db_session.query(Chunk).filter_by(document_id=document_id).count() == 0


def test_delete_nonexistent_document_returns_404(client):
    response = client.delete("/documents/999999")
    assert response.status_code == 404
