from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, LineItem, PolicyRule
from app.ingestion.chunker import chunk_policy_blocks
from app.ingestion.contextual import generate_contextual_text
from app.ingestion.embeddings import embed_documents
from app.ingestion.extraction import (
    extract_bill,
    extract_policy_rules,
    extract_settlement,
)
from app.ingestion.pdf_parser import parse_pdf


def _full_text(blocks) -> str:
    return "\n".join(b.text for b in blocks)


def _ingest_policy(session: Session, document: Document, blocks) -> None:
    document_id = document.id
    full_text = _full_text(blocks)
    # The 1000-char prefix is context for the per-chunk contextual blurb only
    # — it situates a chunk within the document and does not need the whole
    # text. Rule extraction, by contrast, must see the ENTIRE policy: the
    # room-rent-limit / co-pay / sub-limit clauses routinely sit well past the
    # first 1000 characters, and feeding it the prefix silently produced
    # default rules (co_pay_percentage=0.0, sub_limits={}).
    doc_summary = full_text[:1000]
    chunks = chunk_policy_blocks(blocks)
    contextual_texts = [generate_contextual_text(c.text, doc_summary) for c in chunks]
    embeddings = embed_documents(contextual_texts)

    for chunk, ctx_text, embedding in zip(chunks, contextual_texts, embeddings):
        session.add(Chunk(
            document_id=document_id, chunk_text=chunk.text,
            contextual_text=ctx_text, page_number=chunk.page_number,
            embedding=embedding,
        ))

    rules = extract_policy_rules(full_text)
    session.add(PolicyRule(
        document_id=document_id, sum_insured=rules.sum_insured,
        room_rent_limit_per_day=rules.room_rent_limit_per_day,
        room_rent_limit_type=rules.room_rent_limit_type,
        co_pay_percentage=rules.co_pay_percentage,
        sub_limits=rules.sub_limits,
    ))


def _ingest_bill_or_settlement(session: Session, document: Document, doc_type: str, blocks) -> None:
    document_id = document.id
    full_text = _full_text(blocks)
    doc_summary = full_text[:1000]

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
        # Persist the extracted per-day room rent rather than discarding it:
        # the reconciliation engine needs it to compute the room-rent
        # proportionate deduction without assuming a fixed stay length.
        if extraction.room_rent_per_day is not None:
            document.room_rent_per_day = extraction.room_rent_per_day
        for item in extraction.line_items:
            session.add(LineItem(
                document_id=document_id, description=item.description,
                category=item.category, amount=item.amount,
            ))
    else:  # settlement
        extraction = extract_settlement(full_text)
        # Persist the letter's own stated totals. Many real settlement letters
        # (including the generated sample) print only these three totals and
        # no per-item table, so reconstructing the approved amount by summing
        # line items would otherwise produce 0.
        document.settlement_total_claimed = extraction.total_claimed
        document.settlement_total_approved = extraction.total_approved
        document.settlement_total_deducted = extraction.total_deducted
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
            _ingest_policy(session, document, blocks)
        else:
            _ingest_bill_or_settlement(session, document, doc_type, blocks)
        document.status = "indexed"
        session.commit()
        session.execute(sql_text(
            "UPDATE chunks SET search_vector = to_tsvector('english', chunk_text) "
            "WHERE document_id = :doc_id"
        ), {"doc_id": document_id})
        session.commit()
    except Exception:
        session.rollback()
        document.status = "failed"
        session.commit()
        raise
