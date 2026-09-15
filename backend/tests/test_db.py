from app.db.models import Document


def test_insert_and_query_document_round_trip(db_session):
    document = Document(doc_type="bill", filename="sample-bill.pdf", status="processing")
    db_session.add(document)
    db_session.commit()

    fetched = db_session.query(Document).filter_by(filename="sample-bill.pdf").one()

    assert fetched.id == document.id
    assert fetched.doc_type == "bill"
    assert fetched.filename == "sample-bill.pdf"
    assert fetched.status == "processing"
    assert fetched.uploaded_at is not None
