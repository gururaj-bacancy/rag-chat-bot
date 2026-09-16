from app.db.models import Document, LineItem, PolicyRule
from app.reconciliation.engine import reconcile_claim


def _seed_reference_scenario(db_session):
    """Seeds the reference worked example from docs/plan.md's "Reference: Demo
    Reconciliation Numbers" section, with a deliberately wrong settlement
    approved_amount (70000 instead of the correct 75937.50) so a real
    discrepancy is produced."""
    bill = Document(
        doc_type="bill", filename="bill.pdf", status="indexed",
        # Extracted verbatim from the bill ("Room rent (5 days x Rs 8,000/day)")
        # rather than reconstructed by dividing the room_rent total by an
        # assumed stay length.
        room_rent_per_day=8000.0,
    )
    policy = Document(doc_type="policy", filename="policy.pdf", status="indexed")
    settlement = Document(
        doc_type="settlement", filename="settlement.pdf", status="indexed",
        # The totals printed on the settlement letter itself.
        settlement_total_claimed=120000.0,
        settlement_total_approved=70000.0,
        settlement_total_deducted=50000.0,
    )
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


def test_reconcile_claim_uses_extracted_per_day_rate_for_a_non_five_day_stay(db_session):
    """Proves the hardcoded `/ 5` stay-length assumption no longer governs the
    result. A 3-day stay at Rs 10,000/day (room rent total Rs 30,000) against a
    Rs 5,000/day limit and 10% co-pay:

        ratio                   = 5000 / 10000 = 0.5
        proportionate categories= 30000 + 20000 + 12000 + 6000 = 68000
        room rent deduction     = 68000 x (1 - 0.5)            = 34000
        total bill              = 68000 + 9000 + 4000 + 3000   = 84000
        admissible before co-pay= 84000 - 34000                = 50000
        co-pay (10%)            = 5000
        computed approved       = 45000
        settlement states       = 40000  ->  discrepancy 5000

    Under the old `/ 5` heuristic the same rows would imply 30000/5 = Rs
    6,000/day, a ratio of 0.8333, and a computed approval of Rs 65,400 — so
    this test fails loudly if the fallback ever takes precedence again.
    """
    bill = Document(
        doc_type="bill", filename="bill-3day.pdf", status="indexed",
        room_rent_per_day=10000.0,
    )
    policy = Document(doc_type="policy", filename="policy.pdf", status="indexed")
    settlement = Document(
        doc_type="settlement", filename="settlement.pdf", status="indexed",
        settlement_total_claimed=84000.0,
        settlement_total_approved=40000.0,
        settlement_total_deducted=44000.0,
    )
    db_session.add_all([bill, policy, settlement])
    db_session.commit()

    db_session.add_all([
        LineItem(document_id=bill.id, description="Room rent (3 days)", category="room_rent", amount=30000),
        LineItem(document_id=bill.id, description="OT charges", category="ot_charges", amount=20000),
        LineItem(document_id=bill.id, description="Doctor fees", category="doctor_fees", amount=12000),
        LineItem(document_id=bill.id, description="Nursing charges", category="nursing", amount=6000),
        LineItem(document_id=bill.id, description="Medicines", category="medicines", amount=9000),
        LineItem(document_id=bill.id, description="Consumables", category="consumables", amount=4000),
        LineItem(document_id=bill.id, description="Diagnostics", category="diagnostics", amount=3000),
    ])
    db_session.add(PolicyRule(
        document_id=policy.id,
        sum_insured=500000,
        room_rent_limit_per_day=5000,
        room_rent_limit_type="fixed_amount",
        co_pay_percentage=10,
        sub_limits={},
    ))
    db_session.commit()
    db_session.expire_all()

    report = reconcile_claim(db_session)

    assert report is not None
    assert report.room_rent_charged_per_day == 10000.0
    assert round(report.breakdown.room_rent_deduction, 2) == 34000.0
    assert round(report.breakdown.admissible_before_copay, 2) == 50000.0
    assert round(report.breakdown.co_pay_deduction, 2) == 5000.0
    assert round(report.computed_approved_amount, 2) == 45000.0
    assert round(report.actual_approved_amount, 2) == 40000.0
    assert round(report.discrepancy, 2) == 5000.0
    assert report.matches is False
    # Explicitly pin what the old heuristic would have produced, so a
    # regression to `/ 5` can't quietly pass by coincidence.
    assert round(report.computed_approved_amount, 2) != 65400.0


def test_reconcile_claim_falls_back_to_heuristics_when_extracted_totals_absent(db_session):
    """Backward compatibility: documents ingested before the extracted-totals
    columns existed (or bills whose per-day rate the extractor couldn't read)
    have NULL in all four new columns. Those must still reconcile via the old
    room-rent/5 and sum-of-approved-line-items heuristics, reproducing the
    reference numbers exactly."""
    bill = Document(doc_type="bill", filename="bill.pdf", status="indexed")
    policy = Document(doc_type="policy", filename="policy.pdf", status="indexed")
    settlement = Document(doc_type="settlement", filename="settlement.pdf", status="indexed")
    db_session.add_all([bill, policy, settlement])
    db_session.commit()

    assert bill.room_rent_per_day is None
    assert settlement.settlement_total_approved is None

    db_session.add_all([
        LineItem(document_id=bill.id, description="Room rent (5 days)", category="room_rent", amount=40000),
        LineItem(document_id=bill.id, description="OT charges", category="ot_charges", amount=30000),
        LineItem(document_id=bill.id, description="Doctor fees", category="doctor_fees", amount=15000),
        LineItem(document_id=bill.id, description="Nursing charges", category="nursing", amount=10000),
        LineItem(document_id=bill.id, description="Medicines", category="medicines", amount=12000),
        LineItem(document_id=bill.id, description="Consumables", category="consumables", amount=8000),
        LineItem(document_id=bill.id, description="Diagnostics", category="diagnostics", amount=5000),
    ])
    db_session.add(PolicyRule(
        document_id=policy.id,
        sum_insured=500000,
        room_rent_limit_per_day=5000,
        room_rent_limit_type="fixed_amount",
        co_pay_percentage=10,
        sub_limits={},
    ))
    db_session.add(LineItem(
        document_id=settlement.id, description="Total settlement",
        category="settlement_line", amount=120000,
        claimed_amount=120000, approved_amount=70000, deducted_amount=50000,
    ))
    db_session.commit()
    db_session.expire_all()

    report = reconcile_claim(db_session)

    assert report is not None
    assert report.room_rent_charged_per_day == 8000.0  # 40000 / 5
    assert round(report.computed_approved_amount, 2) == 75937.5
    assert round(report.actual_approved_amount, 2) == 70000.0
    assert round(report.discrepancy, 2) == 5937.5


def test_reconcile_claim_works_for_a_settlement_letter_with_totals_but_no_line_items(db_session):
    """The generated sample settlement letter (and many real ones) print only
    three total lines and no per-item table, so extraction produces zero
    settlement LineItem rows. Reconciliation must still run off the stated
    total rather than returning None or silently comparing against 0."""
    bill = Document(
        doc_type="bill", filename="bill.pdf", status="indexed", room_rent_per_day=8000.0,
    )
    policy = Document(doc_type="policy", filename="policy.pdf", status="indexed")
    settlement = Document(
        doc_type="settlement", filename="settlement.pdf", status="indexed",
        settlement_total_claimed=120000.0,
        settlement_total_approved=70000.0,
        settlement_total_deducted=50000.0,
    )
    db_session.add_all([bill, policy, settlement])
    db_session.commit()

    db_session.add_all([
        LineItem(document_id=bill.id, description="Room rent (5 days)", category="room_rent", amount=40000),
        LineItem(document_id=bill.id, description="OT charges", category="ot_charges", amount=30000),
        LineItem(document_id=bill.id, description="Doctor fees", category="doctor_fees", amount=15000),
        LineItem(document_id=bill.id, description="Nursing charges", category="nursing", amount=10000),
        LineItem(document_id=bill.id, description="Medicines", category="medicines", amount=12000),
        LineItem(document_id=bill.id, description="Consumables", category="consumables", amount=8000),
        LineItem(document_id=bill.id, description="Diagnostics", category="diagnostics", amount=5000),
    ])
    db_session.add(PolicyRule(
        document_id=policy.id,
        sum_insured=500000,
        room_rent_limit_per_day=5000,
        room_rent_limit_type="fixed_amount",
        co_pay_percentage=10,
        sub_limits={},
    ))
    db_session.commit()
    db_session.expire_all()

    assert db_session.query(LineItem).filter_by(document_id=settlement.id).count() == 0

    report = reconcile_claim(db_session)

    assert report is not None
    assert round(report.computed_approved_amount, 2) == 75937.5
    assert round(report.actual_approved_amount, 2) == 70000.0
    assert round(report.discrepancy, 2) == 5937.5
    assert report.matches is False


def test_reconcile_claim_report_carries_its_inputs(db_session):
    """docs/design.md Trust & Honesty: the result must expose which numbers it
    was computed from."""
    _seed_reference_scenario(db_session)
    db_session.expire_all()

    report = reconcile_claim(db_session)

    assert report is not None
    assert report.sum_insured == 500000.0
    assert report.room_rent_limit_per_day == 5000.0
    assert report.co_pay_percentage == 10.0
    assert report.room_rent_charged_per_day == 8000.0
