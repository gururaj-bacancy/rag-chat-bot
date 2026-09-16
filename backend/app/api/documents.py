import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile

# Module-attribute import, not `from app.db.session import SessionLocal` /
# `get_session` — see app/db/session.py's get_engine() docstring. Binding a
# bare name at this module's import time (which, for pytest, happens before
# the test-DB fixture reassigns `SessionLocal`) would silently pin every
# request in this router to whatever engine existed at import time. Going
# through the module (`db_session_module.get_session()`) instead resolves the
# current `SessionLocal` at call time, and lets tests `patch.object` it.
from app.db import session as db_session_module
from app.db.models import Document
from app.ingestion.pipeline import ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])

VALID_TYPES = {"bill", "policy", "settlement"}


@router.post("", status_code=201)
def upload_document(file: UploadFile, doc_type: str = Form(...)):
    if doc_type not in VALID_TYPES:
        raise HTTPException(
            status_code=400, detail=f"doc_type must be one of {sorted(VALID_TYPES)}"
        )

    session = db_session_module.get_session()
    try:
        existing = (
            session.query(Document)
            .filter(Document.doc_type == doc_type, Document.status != "failed")
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"An active '{doc_type}' document already exists "
                    f"(id={existing.id}); delete it first."
                ),
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
        return {
            "id": document.id,
            "doc_type": document.doc_type,
            "filename": document.filename,
            "status": document.status,
        }
    finally:
        session.close()


@router.get("")
def list_documents():
    session = db_session_module.get_session()
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
    session = db_session_module.get_session()
    try:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        session.delete(document)
        session.commit()
    finally:
        session.close()
