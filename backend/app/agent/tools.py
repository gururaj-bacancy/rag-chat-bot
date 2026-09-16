import json

from anthropic import beta_tool
from sqlalchemy.orm import Session

from app.db.models import Document
from app.ingestion.embeddings import embed_query
from app.reconciliation.engine import reconcile_claim as run_reconciliation
from app.retrieval.hybrid_search import hybrid_search


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
            # Trust & Honesty (docs/design.md): the reconciliation result must
            # show which numbers it was computed from — the policy's limits and
            # the bill's charged room rate — so the user can check the math
            # themselves instead of taking the output on faith.
            "inputs": {
                "room_rent_limit_per_day": (
                    round(report.room_rent_limit_per_day, 2)
                    if report.room_rent_limit_per_day is not None
                    else None
                ),
                "co_pay_percentage": round(report.co_pay_percentage, 2),
                "sum_insured": round(report.sum_insured, 2),
                "room_rent_charged_per_day": round(report.room_rent_charged_per_day, 2),
            },
            "room_rent_deduction": round(report.breakdown.room_rent_deduction, 2),
            "co_pay_deduction": round(report.breakdown.co_pay_deduction, 2),
            "room_rent_adjustments": [
                {
                    "description": a.description,
                    "original_amount": round(a.original_amount, 2),
                    "eligible_amount": round(a.eligible_amount, 2),
                    "deduction": round(a.deduction, 2),
                }
                for a in report.breakdown.room_rent_adjustments
            ],
        })

    return reconcile_claim
