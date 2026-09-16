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
    # NOTE: days_admitted is not yet modeled as a discrete field (see Open Risks
    # in docs/design.md); this divides the single room_rent line item's total by
    # a fixed 5-day demo stay. A future task could extract `days_admitted`
    # explicitly rather than hardcoding 5.

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
