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
