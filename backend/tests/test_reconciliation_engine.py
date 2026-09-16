from app.db.models import Document, LineItem, PolicyRule
from app.reconciliation.engine import reconcile_claim


def _seed_reference_scenario(db_session):
    """Seeds the reference worked example from docs/plan.md's "Reference: Demo
    Reconciliation Numbers" section, with a deliberately wrong settlement
    approved_amount (70000 instead of the correct 75937.50) so a real
    discrepancy is produced."""
    bill = Document(doc_type="bill", filename="bill.pdf", status="indexed")
    policy = Document(doc_type="policy", filename="policy.pdf", status="indexed")
    settlement = Document(doc_type="settlement", filename="settlement.pdf", status="indexed")
    db_session.add_all([bill, policy, settlement])
    db_session.commit()

    bill_items = [
        LineItem(document_id=bill.id, description="Room rent (5 days)", category="room_rent", amount=40000),
        LineItem(document_id=bill.id, description="OT charges", category="ot_charges", amount=30000),
        LineItem(document_id=bill.id, description="Doctor fees", category="doctor_fees", amount=15000),
        LineItem(document_id=bill.id, description="Nursing charges", category="nursing", amount=10000),
        LineItem(document_id=bill.id, description="Medicines", category="medicines", amount=12000),
        LineItem(document_id=bill.id, description="Consumables", category="consumables", amount=8000),
        LineItem(document_id=bill.id, description="Diagnostics", category="diagnostics", amount=5000),
    ]
    db_session.add_all(bill_items)

    db_session.add(PolicyRule(
        document_id=policy.id,
        sum_insured=500000,
        room_rent_limit_per_day=5000,
        room_rent_limit_type="fixed_amount",
        co_pay_percentage=10,
        sub_limits={},
    ))

    db_session.add(LineItem(
        document_id=settlement.id,
        description="Total settlement",
        category="settlement_line",
        amount=120000,
        claimed_amount=120000,
        approved_amount=70000,
        deducted_amount=50000,
    ))

    db_session.commit()


def test_reconcile_claim_reference_scenario_finds_discrepancy(db_session):
    _seed_reference_scenario(db_session)
    # Force a fresh read from Postgres rather than returning the identity
    # map's already-loaded Python objects (whose numeric attributes would
    # still hold whatever plain int/float they were assigned during seeding).
    # This makes the test genuinely exercise the Decimal->float casts in
    # engine.py: a real requery returns decimal.Decimal for Numeric columns.
    db_session.expire_all()

    report = reconcile_claim(db_session)

    assert report is not None
    assert round(report.computed_approved_amount, 2) == 75937.5
    assert round(report.actual_approved_amount, 2) == 70000.0
    assert round(report.discrepancy, 2) == 5937.5
    assert report.matches is False


def test_reconcile_claim_returns_none_when_documents_missing(db_session):
    bill = Document(doc_type="bill", filename="bill.pdf", status="indexed")
    db_session.add(bill)
    db_session.commit()

    db_session.add(LineItem(
        document_id=bill.id, description="Room rent (5 days)", category="room_rent", amount=40000,
    ))
    db_session.commit()

    report = reconcile_claim(db_session)

    assert report is None
