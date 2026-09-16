from unittest.mock import patch

from app.db.models import Chunk, Document, LineItem, PolicyRule
from app.ingestion.extraction import (
    BillExtraction,
    LineItemExtraction,
    PolicyRuleExtraction,
    SettlementExtraction,
    SettlementLineItemExtraction,
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
    # Rule extraction must see the whole policy, not the 1000-char prefix that
    # is only meant as context for the per-chunk contextual blurbs — clauses
    # like the co-pay percentage routinely sit past that prefix.
    extracted_text = mock_extract_rules.call_args.args[0]
    assert extracted_text == "\n".join(b.text for b in fake_blocks)

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

    # The extracted per-day room rent must be persisted on the document, not
    # discarded: the reconciliation engine uses it instead of assuming a
    # 5-day stay. Note 15000 / 5 would be 3000, so a 5000.0 here can only have
    # come from the extraction result.
    db_session.refresh(document)
    assert float(document.room_rent_per_day) == 5000.0
    assert document.settlement_total_approved is None

    # No policy rule should be created for the bill path.
    assert (
        db_session.query(PolicyRule).filter_by(document_id=document.id).count() == 0
    )


def test_ingest_document_settlement_path(db_session, tmp_path):
    document = Document(
        doc_type="settlement", filename="settlement.pdf", status="processing"
    )
    db_session.add(document)
    db_session.commit()

    fake_blocks = [
        TextBlock(text="CLAIM SETTLEMENT", page_number=1),
        TextBlock(text="Room rent claimed vs approved amounts.", page_number=1),
    ]
    fake_extraction = SettlementExtraction(
        line_items=[
            SettlementLineItemExtraction(
                description="Room rent",
                claimed_amount=15000.0,
                approved_amount=12000.0,
                deducted_amount=3000.0,
                deduction_reason="Room rent capping as per policy",
            ),
        ],
        total_claimed=15000.0,
        total_approved=12000.0,
        total_deducted=3000.0,
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
            "app.ingestion.pipeline.extract_settlement", return_value=fake_extraction
        ) as mock_extract_settlement,
    ):
        ingest_document(db_session, document.id, "settlement", pdf_path)

    mock_parse.assert_called_once_with(pdf_path)
    mock_extract_settlement.assert_called_once()

    assert document.status == "indexed"

    line_item = db_session.query(LineItem).filter_by(document_id=document.id).one()
    assert line_item.category == "settlement_line"
    assert float(line_item.claimed_amount) == 15000.0
    assert float(line_item.approved_amount) == 12000.0
    assert float(line_item.deducted_amount) == 3000.0
    assert line_item.deduction_reason == "Room rent capping as per policy"

    # The letter's own stated totals must be persisted on the document: the
    # reconciliation engine compares against total_approved directly rather
    # than re-deriving it by summing line items.
    db_session.refresh(document)
    assert float(document.settlement_total_claimed) == 15000.0
    assert float(document.settlement_total_approved) == 12000.0
    assert float(document.settlement_total_deducted) == 3000.0
    assert document.room_rent_per_day is None

    # No policy rule should be created for the settlement path.
    assert (
        db_session.query(PolicyRule).filter_by(document_id=document.id).count() == 0
    )


def test_ingest_document_failure_rolls_back_partial_writes(db_session, tmp_path):
    """If extraction fails after chunks were already staged, the failed
    attempt's partial writes must be rolled back — not just left uncommitted
    but actively discarded — before the document is marked 'failed'."""
    document = Document(doc_type="bill", filename="bad-bill.pdf", status="processing")
    db_session.add(document)
    db_session.commit()

    fake_blocks = [
        TextBlock(text="HOSPITAL BILL", page_number=1),
        TextBlock(text="Room rent charges for deluxe room.", page_number=1),
    ]

    pdf_path = _write_fake_pdf(tmp_path)

    with (
        patch("app.ingestion.pipeline.parse_pdf", return_value=fake_blocks),
        patch(
            "app.ingestion.pipeline.generate_contextual_text",
            return_value="Contextualized chunk.",
        ),
        patch(
            "app.ingestion.pipeline.embed_documents",
            return_value=[FAKE_EMBEDDING],
        ),
        patch(
            "app.ingestion.pipeline.extract_bill",
            side_effect=RuntimeError("extraction service unavailable"),
        ),
    ):
        try:
            ingest_document(db_session, document.id, "bill", pdf_path)
            assert False, "expected ingest_document to raise"
        except RuntimeError:
            pass

    assert document.status == "failed"

    # Chunks were staged (session.add'd) before the failure; the exception
    # handler's rollback must have discarded them rather than letting the
    # subsequent status-flip commit persist them.
    assert db_session.query(Chunk).filter_by(document_id=document.id).count() == 0
    assert db_session.query(LineItem).filter_by(document_id=document.id).count() == 0


def test_ingest_document_bill_without_per_day_rate_leaves_column_null(db_session, tmp_path):
    """room_rent_per_day is optional on BillExtraction — a bill that doesn't
    state a per-day rate must leave the column NULL so the engine falls back to
    its heuristic, rather than writing a bogus value."""
    document = Document(doc_type="bill", filename="bill-no-rate.pdf", status="processing")
    db_session.add(document)
    db_session.commit()

    fake_blocks = [
        TextBlock(text="HOSPITAL BILL", page_number=1),
        TextBlock(text="Room rent charges.", page_number=1),
    ]
    fake_extraction = BillExtraction(
        line_items=[
            LineItemExtraction(description="Room rent", category="room_rent", amount=15000.0),
        ],
        room_category=None,
        room_rent_per_day=None,
    )

    pdf_path = _write_fake_pdf(tmp_path)

    with (
        patch("app.ingestion.pipeline.parse_pdf", return_value=fake_blocks),
        patch(
            "app.ingestion.pipeline.generate_contextual_text",
            return_value="Contextualized chunk.",
        ),
        patch("app.ingestion.pipeline.embed_documents", return_value=[FAKE_EMBEDDING]),
        patch("app.ingestion.pipeline.extract_bill", return_value=fake_extraction),
    ):
        ingest_document(db_session, document.id, "bill", pdf_path)

    db_session.refresh(document)
    assert document.status == "indexed"
    assert document.room_rent_per_day is None
