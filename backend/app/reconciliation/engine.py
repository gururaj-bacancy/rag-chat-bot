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
    # The raw inputs the computation was driven by, carried on the report so
    # callers can show which number came from which document rather than
    # presenting the result as a black box (docs/design.md, Trust & Honesty).
    sum_insured: float
    room_rent_limit_per_day: float | None
    co_pay_percentage: float
    room_rent_charged_per_day: float


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
    # A settlement letter that states only totals and prints no per-item table
    # (the shape of the generated sample letter, and of plenty of real ones) is
    # still fully reconcilable, because its stated total_approved is all this
    # comparison needs. Only bail when there is neither a line-item table nor a
    # stated total to compare against.
    if not (bill_items and policy_rule):
        return None
    if not settlement_items and settlement.settlement_total_approved is None:
        return None

    # Prefer the per-day room rent the extractor read off the bill itself.
    # The `/ 5` branch below is only a last-resort fallback for bills where
    # extraction did not surface a per-day figure: it divides the single
    # room_rent line item's total by a fixed 5-day demo stay, and is wrong for
    # any stay that is not 5 days (days_admitted is not modeled as a discrete
    # field — see Open Risks in docs/design.md).
    room_rent_items = [i for i in bill_items if i.category == "room_rent"]
    if bill.room_rent_per_day is not None:
        room_rent_charged_per_day = float(bill.room_rent_per_day)
    else:
        room_rent_charged_per_day = float(room_rent_items[0].amount) / 5 if room_rent_items else 0.0

    rule_items = [RuleLineItem(description=i.description, category=i.category, amount=float(i.amount)) for i in bill_items]
    policy_extraction = PolicyRuleExtraction(
        sum_insured=float(policy_rule.sum_insured),
        room_rent_limit_per_day=float(policy_rule.room_rent_limit_per_day) if policy_rule.room_rent_limit_per_day else None,
        room_rent_limit_type=policy_rule.room_rent_limit_type,
        co_pay_percentage=float(policy_rule.co_pay_percentage),
        sub_limits=policy_rule.sub_limits or {},
    )

    breakdown = compute_admissible_amount(rule_items, policy_extraction, room_rent_charged_per_day)

    # Prefer the total the settlement letter itself states. Summing per-item
    # approved amounts is only a fallback: many letters (including the
    # generated sample) print totals and no per-item table at all, in which
    # case the sum would be 0 and every claim would look wildly under-settled.
    if settlement.settlement_total_approved is not None:
        actual_approved = float(settlement.settlement_total_approved)
    else:
        actual_approved = sum(
            float(i.approved_amount) for i in settlement_items if i.approved_amount is not None
        )
    discrepancy = breakdown.computed_approved_amount - actual_approved

    return ReconciliationReport(
        computed_approved_amount=breakdown.computed_approved_amount,
        actual_approved_amount=actual_approved,
        discrepancy=discrepancy,
        breakdown=breakdown,
        matches=abs(discrepancy) <= TOLERANCE,
        sum_insured=policy_extraction.sum_insured,
        room_rent_limit_per_day=policy_extraction.room_rent_limit_per_day,
        co_pay_percentage=policy_extraction.co_pay_percentage,
        room_rent_charged_per_day=room_rent_charged_per_day,
    )
