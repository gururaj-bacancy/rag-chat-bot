from unittest.mock import patch

from app.db.models import Chunk, Document, LineItem, PolicyRule
from app.ingestion.extraction import (
    BillExtraction,
    LineItemExtraction,
    PolicyRuleExtraction,
)
from app.ingestion.pdf_parser import TextBlock
from app.ingestion.pipeline import ingest_document

FAKE_EMBEDDING = [0.1] * 1024


def _write_fake_pdf(tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    return str(path)


def test_ingest_document_policy_path(db_session, tmp_path):
    document = Document(doc_type="policy", filename="policy.pdf", status="processing")
    db_session.add(document)
    db_session.commit()

    fake_blocks = [
        TextBlock(text="ROOM RENT LIMIT", page_number=1),
        TextBlock(
            text="Room rent is capped at 1% of sum insured per day.",
            page_number=1,
        ),
    ]
    fake_rules = PolicyRuleExtraction(
        sum_insured=500000.0,
        room_rent_limit_per_day=5000.0,
        room_rent_limit_type="fixed_amount",
        co_pay_percentage=10.0,
        sub_limits={"cataract": 25000.0},
    )

    pdf_path = _write_fake_pdf(tmp_path)

    with (
        patch(
            "app.ingestion.pipeline.parse_pdf", return_value=fake_blocks
        ) as mock_parse,
        patch(
            "app.ingestion.pipeline.generate_contextual_text",
            return_value="Contextualized chunk.",
        ),
        patch(
            "app.ingestion.pipeline.embed_documents",
            return_value=[FAKE_EMBEDDING],
        ),
        patch(
            "app.ingestion.pipeline.extract_policy_rules", return_value=fake_rules
        ) as mock_extract_rules,
    ):
        ingest_document(db_session, document.id, "policy", pdf_path)

    mock_parse.assert_called_once_with(pdf_path)
    mock_extract_rules.assert_called_once()

    assert document.status == "indexed"

    chunks = db_session.query(Chunk).filter_by(document_id=document.id).all()
    assert len(chunks) == 1
    assert chunks[0].embedding is not None
    assert chunks[0].contextual_text == "Contextualized chunk."

    rule = db_session.query(PolicyRule).filter_by(document_id=document.id).one()
    assert float(rule.room_rent_limit_per_day) == 5000.0

    # No line items should be created for the policy path.
    assert db_session.query(LineItem).filter_by(document_id=document.id).count() == 0


def test_ingest_document_bill_path(db_session, tmp_path):
    document = Document(doc_type="bill", filename="bill.pdf", status="processing")
    db_session.add(document)
    db_session.commit()

    fake_blocks = [
        TextBlock(text="HOSPITAL BILL", page_number=1),
        TextBlock(text="Room rent charges for deluxe room.", page_number=1),
    ]
    fake_extraction = BillExtraction(
        line_items=[
            LineItemExtraction(
                description="Room rent (Deluxe) x 3 days",
                category="room_rent",
                amount=15000.0,
            ),
        ],
        room_category="Deluxe",
        room_rent_per_day=5000.0,
    )

    pdf_path = _write_fake_pdf(tmp_path)

    with (
        patch(
            "app.ingestion.pipeline.parse_pdf", return_value=fake_blocks
        ) as mock_parse,
        patch(
            "app.ingestion.pipeline.generate_contextual_text",
            return_value="Contextualized chunk.",
        ),
        patch(
            "app.ingestion.pipeline.embed_documents",
            return_value=[FAKE_EMBEDDING],
        ),
        patch(
            "app.ingestion.pipeline.extract_bill", return_value=fake_extraction
        ) as mock_extract_bill,
    ):
        ingest_document(db_session, document.id, "bill", pdf_path)

    mock_parse.assert_called_once_with(pdf_path)
    mock_extract_bill.assert_called_once()

    assert document.status == "indexed"

    line_item = db_session.query(LineItem).filter_by(document_id=document.id).one()
    assert line_item.category == "room_rent"
    assert float(line_item.amount) == 15000.0

    # No policy rule should be created for the bill path.
    assert (
        db_session.query(PolicyRule).filter_by(document_id=document.id).count() == 0
    )
